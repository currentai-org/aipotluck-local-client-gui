//! Talking to the upstream local service on 127.0.0.1:8069.
//!
//! The webview can't call it directly (no CORS headers -- deliberately, it's a localhost-only
//! API), so the UI goes through these commands. Only the routes upstream actually serves are
//! allowed through, so a compromised page can't turn this into a generic localhost proxy.

use serde_json::Value;
use std::time::Duration;

pub const SERVICE_BASE: &str = "http://127.0.0.1:8069";

/// Test-only: a different port for the service, so tools/e2e-smoke.py on a machine that is already
/// set up can never reach (or delete models from) that machine's real service. Unset in normal
/// use; when set, the GUI also hosts the service on it (runtime.rs `spawn_service`).
pub const TEST_PORT_ENV: &str = "AIPOTLUCK_GUI_TEST_SERVICE_PORT";

pub fn test_port() -> Option<u16> {
    std::env::var(TEST_PORT_ENV).ok()?.parse().ok()
}

fn base() -> String {
    match test_port() {
        Some(port) => format!("http://127.0.0.1:{port}"),
        None => SERVICE_BASE.to_string(),
    }
}

/// Route prefixes upstream's `_StatusHandler` serves, per method. Kept in step with upstream by
/// `conformance/` (an unclassified new route fails the surface check).
pub fn allowed(method: &str, path: &str) -> bool {
    let route = path.split('?').next().unwrap_or("");
    if route.contains("..") || !route.starts_with('/') {
        return false;
    }
    match method {
        "GET" => {
            matches!(
                route,
                "/healthz" | "/status" | "/capabilities" | "/models" | "/jobs"
            ) || (route.starts_with("/jobs/")
                && route.len() > "/jobs/".len()
                && !route[6..].contains('/'))
        }
        "POST" => matches!(route, "/models" | "/models/benchmark"),
        "DELETE" => route == "/models",
        _ => false,
    }
}

#[derive(serde::Serialize)]
pub struct ServiceResponse {
    pub status: u16,
    pub body: Value,
}

pub fn call(method: &str, path: &str, body: Option<Value>) -> Result<ServiceResponse, String> {
    if !allowed(method, path) {
        return Err(format!(
            "{method} {path} is not a route the local service serves"
        ));
    }
    let agent = ureq::AgentBuilder::new()
        .timeout_connect(Duration::from_secs(2))
        .timeout(Duration::from_secs(if path.starts_with("/capabilities") {
            60
        } else {
            15
        }))
        .build();
    let url = format!("{}{path}", base());
    let req = agent.request(method, &url);
    let result = match body {
        Some(b) => req.send_json(b),
        None => req.call(),
    };
    let resp = match result {
        Ok(r) => r,
        Err(ureq::Error::Status(_, r)) => r,
        Err(e) => return Err(format!("service unreachable: {e}")),
    };
    let status = resp.status();
    let text = resp.into_string().map_err(|e| e.to_string())?;
    let body = serde_json::from_str(&text).unwrap_or(Value::String(text));
    Ok(ServiceResponse { status, body })
}

pub fn healthy() -> bool {
    matches!(call("GET", "/healthz", None), Ok(r) if r.status == 200)
}

#[cfg(test)]
mod tests {
    use super::allowed;

    /// The port the GUI dials must be the one upstream's service listens on, as recorded in the
    /// committed upstream surface baseline (refreshed by tools/sync_upstream.sh).
    #[test]
    fn service_base_uses_upstreams_default_port() {
        let baseline: serde_json::Value =
            serde_json::from_str(include_str!("../../conformance/upstream-surface.json")).unwrap();
        let port = baseline["service"]["default_port"]
            .as_u64()
            .expect("default_port in baseline");
        assert_eq!(super::SERVICE_BASE, format!("http://127.0.0.1:{port}"));
    }

    /// Every route the proxy allows must be one upstream's handler actually serves.
    #[test]
    fn every_allowed_route_is_served_upstream() {
        let baseline: serde_json::Value =
            serde_json::from_str(include_str!("../../conformance/upstream-surface.json")).unwrap();
        let routes = &baseline["service"]["http_routes"];
        for (method, path) in [
            ("GET", "/healthz"),
            ("GET", "/status"),
            ("GET", "/capabilities"),
            ("GET", "/models"),
            ("GET", "/jobs"),
            ("GET", "/jobs/*"),
            ("POST", "/models"),
            ("POST", "/models/benchmark"),
            ("DELETE", "/models"),
        ] {
            let served = routes[method]
                .as_array()
                .map(|a| a.iter().any(|r| r == path))
                .unwrap_or(false);
            assert!(
                served,
                "{method} {path} is allowed by the proxy but not served upstream"
            );
        }
    }

    #[test]
    fn only_routes_upstream_serves_are_proxied() {
        assert!(allowed("GET", "/status"));
        assert!(allowed("GET", "/jobs/abc123"));
        assert!(allowed("POST", "/models"));
        assert!(allowed("DELETE", "/models?model=org/repo:Q4_K_M"));
    }

    #[test]
    fn anything_else_is_refused_rather_than_forwarded() {
        assert!(!allowed("GET", "/"));
        assert!(!allowed("GET", "/jobs/a/b"));
        assert!(!allowed("GET", "/jobs/"));
        assert!(!allowed("POST", "/status"));
        assert!(!allowed("PUT", "/models"));
        assert!(!allowed("GET", "http://evil/status"));
        assert!(!allowed("GET", "/status/../admin"));
        assert!(!allowed("DELETE", "/jobs/x"));
    }
}
