# v063 desktop daemon (shared by macOS + Windows): push-only peer transport.
#
# The full transport lives in ci/v063/desktop/network.rs (installed below):
# no keepalive pings, no periodic discovery or redial timers. A copy dials each
# paired peer, the link replays the latest clip and closes after a short linger;
# bad frames are skipped, teardown always unregisters, and a newer connection
# replaces a stale one. Regression tests live in that file.
network = PROJECT / "apps/desktop/src/network.rs"
install(LAYER / "desktop/network.rs", network)

# Unit tests exercise handle_connection, which persists peers. Never let a test
# run touch the user's real config directory.
config_rs = PROJECT / "apps/desktop/src/config.rs"
replace_once(
    config_rs,
    '''    fn peers_path() -> Result<PathBuf> {
        let config = Self::path()?;''',
    '''    fn peers_path() -> Result<PathBuf> {
        #[cfg(test)]
        {
            return Ok(std::env::temp_dir().join(format!("clipmesh-unit-tests-{}", std::process::id())).join("peers.json"));
        }
        #[allow(unreachable_code)]
        let config = Self::path()?;''',
    "v063 test-isolated peers path",
)

# On-demand reachability for the UI: `clipmesh probe-peers` (no keys needed).
main_rs = PROJECT / "apps/desktop/src/main.rs"
replace_once(main_rs, "    UiState,\n", "    UiState,\n    ProbePeers,\n", "v063 probe-peers command")
replace_once(
    main_rs,
    "        Command::UiState => ui_state(),\n",
    "        Command::UiState => ui_state(),\n        Command::ProbePeers => probe_peers().await,\n",
    "v063 probe-peers dispatch",
)
replace_once(
    main_rs,
    "fn ui_state()->Result<()> {",
    '''async fn probe_peers()->Result<()> {
    let cfg=Config::load()?;
    for (id,online) in network::probe_peers(&cfg).await {
        println!("PROBE\\t{}\\t{}",id,if online {"online"} else {"offline"});
    }
    Ok(())
}

fn ui_state()->Result<()> {''',
    "v063 probe-peers implementation",
)
