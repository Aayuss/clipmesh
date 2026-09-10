#[cfg(windows)]
fn main() {
    let mut resource = winresource::WindowsResource::new();
    resource.set_icon("assets/clipmesh.ico");
    resource.compile().expect("failed to embed ClipMesh Windows icon");
}

#[cfg(not(windows))]
fn main() {}
