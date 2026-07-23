use serde::Deserialize;
use std::io::BufRead;

pub const PREFIX: &str = "ROSETTA_DESKTOP/1 ";
pub const MAX_LINE_BYTES: usize = 64 * 1024;

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
pub struct Event {
    pub protocol: u8,
    pub event: String,
    pub code: Option<String>,
    pub message: Option<String>,
    pub state: Option<String>,
    pub host: Option<String>,
    pub port: Option<u16>,
    pub admin_url: Option<String>,
    pub health_url: Option<String>,
}

pub fn read_event(reader: &mut impl BufRead) -> Result<Event, String> {
    let mut limited = std::io::Read::take(reader, (MAX_LINE_BYTES + 1) as u64);
    let mut bytes = Vec::new();
    limited
        .read_until(b'\n', &mut bytes)
        .map_err(|_| "sidecar_read_failed".to_string())?;
    if bytes.is_empty() {
        return Err("sidecar_closed".into());
    }
    if bytes.len() > MAX_LINE_BYTES || !bytes.ends_with(b"\n") {
        return Err("sidecar_event_too_large".into());
    }
    let line = std::str::from_utf8(&bytes).map_err(|_| "sidecar_event_encoding".to_string())?;
    let payload = line
        .trim_end_matches(['\r', '\n'])
        .strip_prefix(PREFIX)
        .ok_or_else(|| "sidecar_event_prefix".to_string())?;
    let event: Event =
        serde_json::from_str(payload).map_err(|_| "sidecar_event_json".to_string())?;
    if event.protocol != 1 {
        return Err("sidecar_protocol_version".into());
    }
    Ok(event)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn parses_versioned_event() {
        let mut input =
            Cursor::new(b"ROSETTA_DESKTOP/1 {\"protocol\":1,\"event\":\"ready\",\"port\":8765}\n");
        let event = read_event(&mut input).unwrap();
        assert_eq!(event.event, "ready");
        assert_eq!(event.port, Some(8765));
    }

    #[test]
    fn rejects_unknown_version_and_oversized_line() {
        let mut unknown = Cursor::new(b"ROSETTA_DESKTOP/1 {\"protocol\":2,\"event\":\"ready\"}\n");
        assert_eq!(
            read_event(&mut unknown).unwrap_err(),
            "sidecar_protocol_version"
        );
        let mut oversized = Cursor::new(vec![b'x'; MAX_LINE_BYTES + 1]);
        assert_eq!(
            read_event(&mut oversized).unwrap_err(),
            "sidecar_event_too_large"
        );
    }
}
