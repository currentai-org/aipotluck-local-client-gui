//! The Hugging Face model a person typed into Customize, checked before it goes anywhere near argv.
//!
//! Upstream takes it as `install --model-hf <repo>[:<quant>]`, the same `-hf` shape llama.cpp
//! uses. This accepts exactly that shape, with Hugging Face's own name rules (letters, digits,
//! `-`, `_`, `.`, not starting with `-` or `.`, at most 96 characters). Anything else is refused
//! here, so no input can be read as another flag or a path.

const MAX_PART: usize = 96;
const MAX_QUANT: usize = 64;

fn name_char(c: char) -> bool {
    c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.')
}

fn valid_part(s: &str, max: usize) -> bool {
    !s.is_empty()
        && s.len() <= max
        && s.starts_with(|c: char| c.is_ascii_alphanumeric())
        && s.chars().all(name_char)
        && !s.contains("--")
        && !s.contains("..")
}

/// `Some(trimmed id)` when `raw` is a well-formed `owner/repo[:quant]`, else `None`.
pub fn parse(raw: &str) -> Option<String> {
    let id = raw.trim();
    let (repo, quant) = match id.split_once(':') {
        Some((r, q)) => (r, Some(q)),
        None => (id, None),
    };
    let (owner, name) = repo.split_once('/')?;
    if !valid_part(owner, MAX_PART) || !valid_part(name, MAX_PART) {
        return None;
    }
    if let Some(q) = quant {
        if q.is_empty() || q.len() > MAX_QUANT || !q.chars().all(name_char) {
            return None;
        }
    }
    Some(id.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_the_shapes_upstream_and_llama_cpp_take() {
        assert_eq!(
            parse("bartowski/Qwen2.5-0.5B-Instruct-GGUF:Q4_K_M").as_deref(),
            Some("bartowski/Qwen2.5-0.5B-Instruct-GGUF:Q4_K_M")
        );
        assert_eq!(
            parse("  unsloth/Qwen3-4B-GGUF \n").as_deref(),
            Some("unsloth/Qwen3-4B-GGUF")
        );
        assert!(parse("ggml-org/gemma-3-1b-it-GGUF:q8_0").is_some());
    }

    #[test]
    fn nothing_typed_into_the_model_field_can_become_a_flag_or_a_path() {
        for bad in [
            "--system",
            "-x/y",
            "org/--no-service",
            "../etc/passwd",
            "org/../../x",
            "/abs/path.gguf",
            "org/repo/extra",
            "org/repo:Q4 --system",
            "org/repo;rm -rf ~",
            "org/repo:",
            "org/repo:Q4:extra",
            "org repo",
            "just-a-name",
            "",
            "https://huggingface.co/org/repo",
        ] {
            assert_eq!(parse(bad), None, "{bad:?} must be refused");
        }
    }

    #[test]
    fn overlong_names_are_refused() {
        let long = "a".repeat(MAX_PART + 1);
        assert_eq!(parse(&format!("{long}/repo")), None);
        assert_eq!(parse(&format!("org/{long}")), None);
        assert!(parse(&format!("org/{}", "a".repeat(MAX_PART))).is_some());
    }
}
