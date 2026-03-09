// frontend/src-tauri/src/main.rs
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::{Manager, async_runtime};
use std::fs;
use std::path::PathBuf;
use std::thread;
use std::time::Duration;

#[tauri::command]
fn get_backend_port() -> Result<u16, String> {
    let port_file = dirs::home_dir()
        .ok_or("Cannot find home directory")?
        .join(".owl_backend_port");
    
    // 等待端口文件生成（最多 10 秒）
    for _ in 0..100 {
        if port_file.exists() {
            let content = fs::read_to_string(&port_file)
                .map_err(|e| format!("Failed to read port file: {}", e))?;
            let port: u16 = content.trim().parse()
                .map_err(|e| format!("Invalid port number: {}", e))?;
            return Ok(port);
        }
        thread::sleep(Duration::from_millis(100));
    }
    
    Err("Backend failed to start within 10 seconds".to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            // 启动 Python Sidecar
            let sidecar = app.shell()
                .sidecar("python-backend")
                .expect("Failed to create sidecar command");
            
            let (mut rx, _child) = sidecar
                .spawn()
                .expect("Failed to spawn sidecar");
            
            // 监听 Sidecar 输出
            async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    match event {
                        tauri_plugin_shell::ShellEvent::Stdout(line) => {
                            println!("[Python] {}", String::from_utf8_lossy(&line));
                        }
                        tauri_plugin_shell::ShellEvent::Stderr(line) => {
                            eprintln!("[Python] {}", String::from_utf8_lossy(&line));
                        }
                        tauri_plugin_shell::ShellEvent::Error(err) => {
                            eprintln!("[Python Error] {}", err);
                        }
                        tauri_plugin_shell::ShellEvent::Terminated(payload) => {
                            println!("[Python] Terminated with code: {:?}", payload.code);
                        }
                        _ => {}
                    }
                }
            });
            
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![get_backend_port])
        .run(tauri::generate_context!())
        .expect("Error while running Tauri application");
}