use crate::navigation::validate_admin_url;
use crate::protocol::{Event, read_event};
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::Path;
use std::process::{Child, Command, ExitStatus, Stdio};
use std::sync::mpsc;
use std::time::{Duration, Instant};

const START_TIMEOUT: Duration = Duration::from_secs(20);
const STOP_TIMEOUT: Duration = Duration::from_secs(8);
const ACTION_TIMEOUT: Duration = Duration::from_secs(20);
const REAP_TIMEOUT: Duration = Duration::from_secs(2);
const HEALTH_TIMEOUT: Duration = Duration::from_secs(3);
const WAIT_POLL_INTERVAL: Duration = Duration::from_millis(10);

/// Owns a sidecar process and guarantees a bounded kill-and-wait on every drop path.
struct ManagedChild {
    child: Child,
    reaped: bool,
}

impl ManagedChild {
    fn spawn(binary: &Path, action: &str, config_dir: &Path) -> Result<Self, String> {
        let child = Command::new(binary)
            .args([action, "--config"])
            .arg(config_dir)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|_| "sidecar_spawn_failed".to_string())?;
        Ok(Self {
            child,
            reaped: false,
        })
    }

    fn wait_bounded(&mut self, timeout: Duration) -> Result<ExitStatus, String> {
        let deadline = Instant::now() + timeout;
        loop {
            match self.child.try_wait() {
                Ok(Some(status)) => {
                    self.reaped = true;
                    return Ok(status);
                }
                Ok(None) if Instant::now() < deadline => {
                    std::thread::sleep(WAIT_POLL_INTERVAL.min(timeout));
                }
                Ok(None) => return Err("sidecar_wait_timeout".to_string()),
                Err(_) => return Err("sidecar_wait_failed".to_string()),
            }
        }
    }

    fn terminate_and_reap(&mut self, timeout: Duration) -> Result<(), String> {
        if self.reaped {
            return Ok(());
        }
        match self.child.try_wait() {
            Ok(Some(_)) => {
                self.reaped = true;
                return Ok(());
            }
            Ok(None) => {}
            Err(_) => return Err("sidecar_wait_failed".to_string()),
        }

        let kill_error = self.child.kill().err();
        match self.wait_bounded(timeout) {
            Ok(_) => Ok(()),
            Err(error) => {
                if kill_error.is_some() {
                    Err("sidecar_kill_failed".to_string())
                } else {
                    Err(error)
                }
            }
        }
    }
}

impl Drop for ManagedChild {
    fn drop(&mut self) {
        let _ = self.terminate_and_reap(REAP_TIMEOUT);
    }
}

fn read_event_with_timeout(
    mut reader: BufReader<std::process::ChildStdout>,
    timeout: Duration,
) -> Result<(Event, BufReader<std::process::ChildStdout>), String> {
    let (sender, receiver) = mpsc::sync_channel(1);
    std::thread::spawn(move || {
        let result = read_event(&mut reader);
        let _ = sender.send((result, reader));
    });
    let (event, reader) = receiver
        .recv_timeout(timeout)
        .map_err(|_| "sidecar_event_timeout".to_string())?;
    Ok((event?, reader))
}

fn health_live(admin_url: &str) -> Result<(), String> {
    let parsed = url::Url::parse(admin_url).map_err(|_| "invalid_admin_url".to_string())?;
    let port = parsed
        .port()
        .ok_or_else(|| "invalid_admin_port".to_string())?;
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let mut stream = TcpStream::connect_timeout(&address, HEALTH_TIMEOUT)
        .map_err(|_| "sidecar_health_connect".to_string())?;
    stream
        .set_read_timeout(Some(HEALTH_TIMEOUT))
        .map_err(|_| "sidecar_health_timeout".to_string())?;
    stream
        .set_write_timeout(Some(HEALTH_TIMEOUT))
        .map_err(|_| "sidecar_health_timeout".to_string())?;
    stream
        .write_all(b"GET /health/live HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .map_err(|_| "sidecar_health_write".to_string())?;
    let mut reader = BufReader::new(stream);
    let mut status = String::new();
    reader
        .read_line(&mut status)
        .map_err(|_| "sidecar_health_read".to_string())?;
    if !status.starts_with("HTTP/1.1 200 ") && !status.starts_with("HTTP/1.0 200 ") {
        return Err("sidecar_health_status".to_string());
    }
    let mut discard = Vec::new();
    let _ = reader.take(4096).read_to_end(&mut discard);
    Ok(())
}

pub struct SidecarSupervisor {
    child: ManagedChild,
    ready: Event,
    stdout: Option<BufReader<std::process::ChildStdout>>,
}

impl SidecarSupervisor {
    pub fn start(binary: &Path, config_dir: &Path) -> Result<Self, String> {
        Self::start_with_health(binary, config_dir, START_TIMEOUT, health_live)
    }

    fn start_with_health<F>(
        binary: &Path,
        config_dir: &Path,
        event_timeout: Duration,
        health_check: F,
    ) -> Result<Self, String>
    where
        F: FnOnce(&str) -> Result<(), String>,
    {
        let mut child = ManagedChild::spawn(binary, "serve", config_dir)?;
        let stdout = child
            .child
            .stdout
            .take()
            .ok_or_else(|| "sidecar_stdout".to_string())?;
        let (ready, stdout) = read_event_with_timeout(BufReader::new(stdout), event_timeout)?;
        if ready.event != "ready" {
            return Err(ready.code.unwrap_or_else(|| "sidecar_not_ready".into()));
        }
        let url = ready
            .admin_url
            .as_deref()
            .ok_or_else(|| "missing_admin_url".to_string())?;
        validate_admin_url(url)?;
        health_check(url)?;
        Ok(Self {
            child,
            ready,
            stdout: Some(stdout),
        })
    }

    pub fn admin_url(&self) -> &str {
        self.ready
            .admin_url
            .as_deref()
            .expect("validated ready event")
    }

    pub fn shutdown(&mut self) -> Result<(), String> {
        self.shutdown_with_timeout(STOP_TIMEOUT)
    }

    fn shutdown_with_timeout(&mut self, timeout: Duration) -> Result<(), String> {
        let result = self.shutdown_inner(timeout);
        if let Err(error) = result {
            return match self.child.terminate_and_reap(REAP_TIMEOUT) {
                Ok(()) => Err(error),
                Err(cleanup_error) => Err(cleanup_error),
            };
        }
        Ok(())
    }

    fn shutdown_inner(&mut self, timeout: Duration) -> Result<(), String> {
        let stdin = self
            .child
            .child
            .stdin
            .as_mut()
            .ok_or_else(|| "sidecar_shutdown_stdin".to_string())?;
        stdin
            .write_all(b"{\"command\":\"shutdown\"}\n")
            .and_then(|_| stdin.flush())
            .map_err(|_| "sidecar_shutdown_write".to_string())?;
        let reader = self
            .stdout
            .take()
            .ok_or_else(|| "sidecar_shutdown_reader".to_string())?;
        let (stopped, reader) = read_event_with_timeout(reader, timeout)?;
        self.stdout = Some(reader);
        if stopped.event != "stopped" {
            return Err("sidecar_shutdown_event".to_string());
        }
        let status = self.child.wait_bounded(timeout)?;
        if !status.success() {
            return Err("sidecar_shutdown_failed".to_string());
        }
        Ok(())
    }
}

impl Drop for SidecarSupervisor {
    fn drop(&mut self) {
        let _ = self.child.terminate_and_reap(REAP_TIMEOUT);
    }
}

pub fn run_action(
    binary: &Path,
    action: &str,
    config_dir: &Path,
    command: Option<&serde_json::Value>,
) -> Result<Event, String> {
    run_action_with_timeout(binary, action, config_dir, command, ACTION_TIMEOUT)
}

fn run_action_with_timeout(
    binary: &Path,
    action: &str,
    config_dir: &Path,
    command: Option<&serde_json::Value>,
    timeout: Duration,
) -> Result<Event, String> {
    let expected_event = match action {
        "probe" => "probe",
        "init" => "initialized",
        "confirm-local-mode" => "local_mode",
        _ => return Err("invalid_sidecar_action".into()),
    };
    let mut child = ManagedChild::spawn(binary, action, config_dir)?;
    if let Some(command) = command {
        let stdin = child
            .child
            .stdin
            .as_mut()
            .ok_or_else(|| "sidecar_stdin".to_string())?;
        serde_json::to_writer(&mut *stdin, command)
            .map_err(|_| "sidecar_command_json".to_string())?;
        stdin
            .write_all(b"\n")
            .and_then(|_| stdin.flush())
            .map_err(|_| "sidecar_command_write".to_string())?;
    }
    drop(child.child.stdin.take());
    let stdout = child
        .child
        .stdout
        .take()
        .ok_or_else(|| "sidecar_stdout".to_string())?;
    let (event, _) = read_event_with_timeout(BufReader::new(stdout), timeout)?;
    let status = child.wait_bounded(timeout)?;
    if !status.success() && event.event != "error" {
        return Err("sidecar_action_failed".into());
    }
    if event.event != expected_event && event.event != "error" {
        return Err("sidecar_action_event".into());
    }
    Ok(event)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::sync::{Mutex, MutexGuard, OnceLock};

    static FAKE_SIDECAR_LOCK: Mutex<()> = Mutex::new(());
    static FAKE_SIDECAR: OnceLock<PathBuf> = OnceLock::new();

    fn lock_fake_sidecar() -> MutexGuard<'static, ()> {
        FAKE_SIDECAR_LOCK
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    fn fake_sidecar() -> &'static Path {
        FAKE_SIDECAR
            .get_or_init(|| {
                let directory = tempfile::tempdir().unwrap().keep();
                let source = directory.join("fake_sidecar.rs");
                let binary =
                    directory.join(format!("fake-sidecar{}", std::env::consts::EXE_SUFFIX));
                fs::write(
                    &source,
                    r#"
use std::io::{self, BufRead, Write};
use std::thread;
use std::time::Duration;

fn emit(event: &str, extra: &str) {
    println!(
        "ROSETTA_DESKTOP/1 {{\"protocol\":1,\"event\":\"{}\"{}}}",
        event, extra
    );
    io::stdout().flush().unwrap();
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let scenario = args.last().map(String::as_str).unwrap_or("");
    match scenario {
        "success" => emit("probe", ",\"state\":\"ready\""),
        "event-timeout" => thread::sleep(Duration::from_secs(10)),
        "malformed" => {
            println!("not-a-protocol-event");
            io::stdout().flush().unwrap();
            thread::sleep(Duration::from_secs(10));
        }
        "unexpected-action" => emit("initialized", ""),
        "nonzero" => {
            emit("probe", "");
            std::process::exit(7);
        }
        "exit-timeout" => {
            emit("probe", "");
            thread::sleep(Duration::from_secs(10));
        }
        "invalid-url" => {
            emit("ready", ",\"admin_url\":\"https://example.com/admin/\"");
            thread::sleep(Duration::from_secs(10));
        }
        "unexpected-ready" => {
            emit("probe", "");
            thread::sleep(Duration::from_secs(10));
        }
        "shutdown-timeout" => {
            emit("ready", ",\"admin_url\":\"http://127.0.0.1:8765/admin/\"");
            let _ = io::stdin().lock().lines().next();
            thread::sleep(Duration::from_secs(10));
        }
        "supervisor-success" => {
            emit("ready", ",\"admin_url\":\"http://127.0.0.1:8765/admin/\"");
            let _ = io::stdin().lock().lines().next();
            emit("stopped", "");
        }
        _ => std::process::exit(2),
    }
}
"#,
                )
                .unwrap();
                let status =
                    Command::new(std::env::var_os("RUSTC").unwrap_or_else(|| "rustc".into()))
                        .args(["--edition", "2024"])
                        .arg(&source)
                        .arg("-o")
                        .arg(&binary)
                        .status()
                        .unwrap();
                assert!(status.success(), "failed to compile fake sidecar");
                binary
            })
            .as_path()
    }

    #[test]
    fn fake_sidecar_action_success_is_reaped() {
        let _lock = lock_fake_sidecar();
        let result = run_action_with_timeout(
            fake_sidecar(),
            "probe",
            Path::new("success"),
            None,
            Duration::from_secs(1),
        )
        .unwrap();
        assert_eq!(result.event, "probe");
    }

    #[test]
    fn fake_sidecar_action_timeout_is_bounded_and_reaped() {
        let _lock = lock_fake_sidecar();
        let started = Instant::now();
        let error = run_action_with_timeout(
            fake_sidecar(),
            "probe",
            Path::new("event-timeout"),
            None,
            Duration::from_millis(500),
        )
        .unwrap_err();
        assert_eq!(error, "sidecar_event_timeout");
        assert!(started.elapsed() < Duration::from_secs(3));
    }

    #[test]
    fn fake_sidecar_malformed_event_is_reaped() {
        let _lock = lock_fake_sidecar();
        let error = run_action_with_timeout(
            fake_sidecar(),
            "probe",
            Path::new("malformed"),
            None,
            Duration::from_secs(1),
        )
        .unwrap_err();
        assert_eq!(error, "sidecar_event_prefix");
    }

    #[test]
    fn fake_sidecar_unexpected_action_event_is_rejected() {
        let _lock = lock_fake_sidecar();
        let error = run_action_with_timeout(
            fake_sidecar(),
            "probe",
            Path::new("unexpected-action"),
            None,
            Duration::from_secs(1),
        )
        .unwrap_err();
        assert_eq!(error, "sidecar_action_event");
    }

    #[test]
    fn fake_sidecar_nonzero_exit_is_rejected_after_reap() {
        let _lock = lock_fake_sidecar();
        let error = run_action_with_timeout(
            fake_sidecar(),
            "probe",
            Path::new("nonzero"),
            None,
            Duration::from_secs(1),
        )
        .unwrap_err();
        assert_eq!(error, "sidecar_action_failed");
    }

    #[test]
    fn fake_sidecar_action_exit_timeout_is_bounded_and_reaped() {
        let _lock = lock_fake_sidecar();
        let started = Instant::now();
        let error = run_action_with_timeout(
            fake_sidecar(),
            "probe",
            Path::new("exit-timeout"),
            None,
            Duration::from_millis(500),
        )
        .unwrap_err();
        assert_eq!(error, "sidecar_wait_timeout");
        assert!(started.elapsed() < Duration::from_secs(3));
    }

    #[test]
    fn fake_sidecar_invalid_ready_url_is_reaped() {
        let _lock = lock_fake_sidecar();
        let error = SidecarSupervisor::start_with_health(
            fake_sidecar(),
            Path::new("invalid-url"),
            Duration::from_secs(1),
            |_| Ok(()),
        )
        .err()
        .expect("invalid ready URL must fail");
        assert_eq!(error, "invalid_admin_url");
    }

    #[test]
    fn fake_sidecar_unexpected_ready_event_is_reaped() {
        let _lock = lock_fake_sidecar();
        let error = SidecarSupervisor::start_with_health(
            fake_sidecar(),
            Path::new("unexpected-ready"),
            Duration::from_secs(1),
            |_| Ok(()),
        )
        .err()
        .expect("unexpected ready event must fail");
        assert_eq!(error, "sidecar_not_ready");
    }

    #[test]
    fn fake_sidecar_shutdown_timeout_is_bounded_and_reaped() {
        let _lock = lock_fake_sidecar();
        let mut supervisor = SidecarSupervisor::start_with_health(
            fake_sidecar(),
            Path::new("shutdown-timeout"),
            Duration::from_secs(1),
            |_| Ok(()),
        )
        .unwrap();
        let started = Instant::now();
        let error = supervisor
            .shutdown_with_timeout(Duration::from_millis(50))
            .unwrap_err();
        assert_eq!(error, "sidecar_event_timeout");
        assert!(started.elapsed() < Duration::from_secs(3));
        assert!(supervisor.child.reaped);
    }

    #[test]
    fn fake_sidecar_supervisor_successfully_stops_and_reaps() {
        let _lock = lock_fake_sidecar();
        let mut supervisor = SidecarSupervisor::start_with_health(
            fake_sidecar(),
            Path::new("supervisor-success"),
            Duration::from_secs(1),
            |_| Ok(()),
        )
        .unwrap();
        supervisor
            .shutdown_with_timeout(Duration::from_secs(1))
            .unwrap();
        assert!(supervisor.child.reaped);
    }
}
