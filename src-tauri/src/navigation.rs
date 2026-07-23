use url::Url;

pub fn validate_admin_url(value: &str) -> Result<Url, String> {
    let url = Url::parse(value).map_err(|_| "invalid_admin_url".to_string())?;
    if url.scheme() != "http"
        || url.host_str() != Some("127.0.0.1")
        || url.port().is_none()
        || !matches!(url.path(), "/admin" | "/admin/")
        || url.query().is_some()
        || url.fragment().is_some()
        || !url.username().is_empty()
        || url.password().is_some()
    {
        return Err("invalid_admin_url".into());
    }
    Ok(url)
}

pub fn navigation_is_allowed(candidate: &Url, owned_admin: &Url) -> bool {
    candidate.origin() == owned_admin.origin()
        && (candidate.path() == "/admin"
            || candidate.path() == "/admin/"
            || candidate.path().starts_with("/admin/"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_only_exact_owned_loopback_entry() {
        let owned = validate_admin_url("http://127.0.0.1:8765/admin").unwrap();
        assert!(navigation_is_allowed(
            &Url::parse("http://127.0.0.1:8765/admin/models").unwrap(),
            &owned
        ));
        assert!(!navigation_is_allowed(
            &Url::parse("http://127.0.0.1:8766/admin").unwrap(),
            &owned
        ));
        assert!(validate_admin_url("http://localhost:8765/admin").is_err());
        assert!(validate_admin_url("https://127.0.0.1:8765/admin").is_err());
    }
}
