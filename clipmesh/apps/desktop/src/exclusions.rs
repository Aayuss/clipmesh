use active_win_pos_rs::get_active_window;

pub fn active_app() -> Option<String> {
    let win = get_active_window().ok()?;
    let path = win.process_path.to_string_lossy();
    Some(format!("{} | {}", win.app_name, path))
}

pub fn is_excluded(source: Option<&str>, exclusions: &[String]) -> bool {
    let Some(source) = source else { return false; };
    let source = source.to_ascii_lowercase();
    exclusions.iter().any(|e| {
        let e=e.trim().to_ascii_lowercase();
        !e.is_empty() && source.contains(&e)
    })
}
