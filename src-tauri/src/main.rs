use codex_rosetta_desktop::navigation::{navigation_is_allowed, validate_admin_url};
use codex_rosetta_desktop::sidecar::{SidecarSupervisor, run_action};
use serde::Serialize;
use serde_json::json;
use std::path::PathBuf;
use std::sync::Mutex;
use tauri::{Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder};

struct DesktopState {
    sidecar: Mutex<Option<SidecarSupervisor>>,
}

#[derive(Serialize)]
struct BootstrapResult {
    event: String,
    state: Option<String>,
    code: Option<String>,
}

fn ensure_bootstrap(window: &WebviewWindow) -> Result<(), String> {
    if window.label() != "bootstrap" {
        return Err("bootstrap_capability_required".into());
    }
    Ok(())
}

fn sidecar_binary(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    #[cfg(debug_assertions)]
    if let Some(path) = std::env::var_os("ROSETTA_DESKTOP_SIDECAR") {
        return Ok(PathBuf::from(path));
    }
    let suffix = option_env!("TAURI_ENV_TARGET_TRIPLE").unwrap_or("unknown-target");
    let name = if cfg!(windows) {
        format!("codex-rosetta-desktop-sidecar-{suffix}.exe")
    } else {
        format!("codex-rosetta-desktop-sidecar-{suffix}")
    };
    let candidate = app
        .path()
        .resource_dir()
        .map_err(|_| "sidecar_path".to_string())?
        .join("binaries")
        .join(name);
    if !candidate.is_file() {
        return Err("sidecar_path".to_string());
    }
    Ok(candidate)
}

fn config_dir(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_config_dir()
        .map_err(|_| "config_dir".to_string())
}

#[tauri::command]
fn probe(window: WebviewWindow, app: tauri::AppHandle) -> Result<BootstrapResult, String> {
    ensure_bootstrap(&window)?;
    let event = run_action(&sidecar_binary(&app)?, "probe", &config_dir(&app)?, None)?;
    Ok(BootstrapResult {
        event: event.event,
        state: event.state,
        code: event.code,
    })
}

#[tauri::command]
fn initialize(
    window: WebviewWindow,
    app: tauri::AppHandle,
    admin_password: String,
) -> Result<BootstrapResult, String> {
    ensure_bootstrap(&window)?;
    let event = run_action(
        &sidecar_binary(&app)?,
        "init",
        &config_dir(&app)?,
        Some(&json!({"command": "init", "admin_password": admin_password})),
    )?;
    Ok(BootstrapResult {
        event: event.event,
        state: event.state,
        code: event.code,
    })
}

#[tauri::command]
fn confirm_local_mode(
    window: WebviewWindow,
    app: tauri::AppHandle,
    confirm: bool,
) -> Result<BootstrapResult, String> {
    ensure_bootstrap(&window)?;
    let event = run_action(
        &sidecar_binary(&app)?,
        "confirm-local-mode",
        &config_dir(&app)?,
        Some(&json!({"command": "confirm_local_mode", "confirm": confirm})),
    )?;
    Ok(BootstrapResult {
        event: event.event,
        state: event.state,
        code: event.code,
    })
}

#[tauri::command]
fn start_gateway(
    window: WebviewWindow,
    app: tauri::AppHandle,
    state: tauri::State<DesktopState>,
) -> Result<(), String> {
    ensure_bootstrap(&window)?;
    let supervisor = SidecarSupervisor::start(&sidecar_binary(&app)?, &config_dir(&app)?)?;
    let owned = validate_admin_url(supervisor.admin_url())?;
    let navigation_origin = owned.clone();
    WebviewWindowBuilder::new(&app, "admin", WebviewUrl::External(owned.clone()))
        .title("Codex-Rosetta")
        .inner_size(1180.0, 780.0)
        .on_navigation(move |candidate| navigation_is_allowed(candidate, &navigation_origin))
        .build()
        .map_err(|_| "admin_window_create".to_string())?;
    *state
        .sidecar
        .lock()
        .map_err(|_| "sidecar_state".to_string())? = Some(supervisor);
    window.close().map_err(|_| "bootstrap_close".to_string())?;
    Ok(())
}

fn main() {
    let app = tauri::Builder::default()
        .manage(DesktopState {
            sidecar: Mutex::new(None),
        })
        .invoke_handler(tauri::generate_handler![
            probe,
            initialize,
            confirm_local_mode,
            start_gateway
        ])
        .build(tauri::generate_context!())
        .expect("failed to build Codex-Rosetta desktop shell");
    app.run(|handle, event| {
        if matches!(event, tauri::RunEvent::ExitRequested { .. })
            && let Some(state) = handle.try_state::<DesktopState>()
            && let Ok(mut guard) = state.sidecar.lock()
            && let Some(mut supervisor) = guard.take()
        {
            let _ = supervisor.shutdown();
        }
    });
}
