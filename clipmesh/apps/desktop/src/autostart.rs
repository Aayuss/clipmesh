use anyhow::{bail, Context, Result};
use std::{env, fs, process::Command};

pub fn install() -> Result<()> {
    let exe=env::current_exe()?.canonicalize()?;
    #[cfg(target_os="macos")]
    {
        let home=env::var("HOME")?;
        let dir=std::path::Path::new(&home).join("Library/LaunchAgents"); fs::create_dir_all(&dir)?;
        let path=dir.join("dev.clipmesh.agent.plist");
        let xml=format!(r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>dev.clipmesh.agent</string>
<key>ProgramArguments</key><array><string>{}</string><string>run</string></array>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
<key>ProcessType</key><string>Background</string>
</dict></plist>"#,xml_escape(&exe.to_string_lossy()));
        fs::write(&path,xml)?;
        let _=Command::new("launchctl").args(["unload",path.to_string_lossy().as_ref()]).status();
        Command::new("launchctl").args(["load",path.to_string_lossy().as_ref()]).status().context("launchctl")?;
        println!("Installed {}",path.display()); return Ok(());
    }
    #[cfg(target_os="windows")]
    {
        let value=format!("\"{}\" run",exe.display());
        let status=Command::new("reg").args(["add",r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run","/v","ClipMesh","/t","REG_SZ","/d",&value,"/f"]).status()?;
        if !status.success(){bail!("failed to install Run key");} println!("Installed Windows startup entry"); return Ok(());
    }
    #[allow(unreachable_code)] bail!("autostart installer supports macOS and Windows")
}

pub fn uninstall() -> Result<()> {
    #[cfg(target_os="macos")]
    {
        let home=env::var("HOME")?; let path=std::path::Path::new(&home).join("Library/LaunchAgents/dev.clipmesh.agent.plist");
        let _=Command::new("launchctl").args(["unload",path.to_string_lossy().as_ref()]).status(); let _=fs::remove_file(&path); println!("Removed {}",path.display()); return Ok(());
    }
    #[cfg(target_os="windows")]
    { let _=Command::new("reg").args(["delete",r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run","/v","ClipMesh","/f"]).status(); println!("Removed Windows startup entry"); return Ok(()); }
    #[allow(unreachable_code)] bail!("autostart installer supports macOS and Windows")
}

#[cfg(target_os="macos")]
fn xml_escape(s:&str)->String{s.replace('&',"&amp;").replace('<',"&lt;").replace('>',"&gt;").replace('"',"&quot;")}
