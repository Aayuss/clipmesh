from pathlib import Path
import os
import platform


root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"
system = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def replace(path: Path, old: str, new: str, label: str, count=1):
    text = path.read_text(encoding="utf-8")
    found = text.count(old)
    if found != count:
        raise SystemExit(f"{label}: expected {count} match(es) in {path}, found {found}")
    path.write_text(text.replace(old, new, count), encoding="utf-8")


if system == "Linux":
    java = project / "android/app/src/main/java/dev/clipmesh"
    runtime = java / "BackgroundRuntime.kt"
    incoming = java / "fileshare/IncomingRequestUi.kt"
    access = java / "exclusion/ExclusionAccessibilityService.kt"
    engine = java / "fileshare/LocalTransferEngine.kt"

    # UI visibility must represent the whole ClipMesh process, not the lifetime of
    # the incoming-request helper. Android can keep an Activity instance alive
    # after BACK while it is already stopped, which left `visible=true` forever.
    # Track every started ClipMesh Activity by identity. The current Activity is
    # seeded when BackgroundRuntime is first entered from onResume, covering the
    # case where lifecycle callbacks were installed after that Activity's onStart.
    # A short delayed hide absorbs normal Main/File/Settings transitions.
    replace(
        runtime,
        "object BackgroundRuntime {\n",
        r'''private object ClipMeshUiVisibility : android.app.Application.ActivityLifecycleCallbacks {
    @Volatile private var installed = false
    private val startedActivities = java.util.Collections.newSetFromMap(
        java.util.IdentityHashMap<android.app.Activity, Boolean>()
    )
    private var hideGeneration = 0L

    fun install(context: Context) {
        val application = context.applicationContext as? android.app.Application ?: return
        var register = false
        var foreground = false
        synchronized(this) {
            if (!installed) {
                installed = true
                register = true
            }
            if (context is android.app.Activity) {
                startedActivities.add(context)
                hideGeneration += 1
                foreground = true
            }
        }
        if (register) application.registerActivityLifecycleCallbacks(this)
        if (foreground) LocalTransferEngine.setUiVisible(true)
    }

    override fun onActivityStarted(activity: android.app.Activity) {
        synchronized(this) {
            startedActivities.add(activity)
            hideGeneration += 1
        }
        LocalTransferEngine.setUiVisible(true)
    }

    override fun onActivityStopped(activity: android.app.Activity) {
        var generation = 0L
        var shouldScheduleHide = false
        synchronized(this) {
            startedActivities.remove(activity)
            hideGeneration += 1
            generation = hideGeneration
            shouldScheduleHide = startedActivities.isEmpty()
        }
        if (!shouldScheduleHide) return
        android.os.Handler(android.os.Looper.getMainLooper()).postDelayed({
            val stillHidden = synchronized(this) {
                startedActivities.isEmpty() && hideGeneration == generation
            }
            if (stillHidden) LocalTransferEngine.setUiVisible(false)
        }, 350L)
    }

    override fun onActivityCreated(activity: android.app.Activity, state: android.os.Bundle?) = Unit
    override fun onActivityResumed(activity: android.app.Activity) = Unit
    override fun onActivityPaused(activity: android.app.Activity) = Unit
    override fun onActivitySaveInstanceState(activity: android.app.Activity, state: android.os.Bundle) = Unit
    override fun onActivityDestroyed(activity: android.app.Activity) {
        synchronized(this) { startedActivities.remove(activity) }
    }
}

object BackgroundRuntime {
''',
        "Android process UI visibility tracker",
    )
    replace(
        runtime,
        "        if (SettingsStore(app).receiveFilesInBackground) LocalTransferEngine.start(app) else LocalTransferEngine.stop()\n",
        """        if (SettingsStore(app).receiveFilesInBackground) LocalTransferEngine.start(app) else LocalTransferEngine.stop()
        ClipMeshUiVisibility.install(context)
""",
        "Android UI visibility tracker install",
    )

    # IncomingRequestUi owns only the weak Activity used to show confirmation UI.
    # It must not own global app visibility because detach is not an onStop signal.
    replace(
        incoming,
        """    fun attach(activity: Activity) {
        visible = WeakReference<Activity?>(activity)
        LocalTransferEngine.setUiVisible(true)
    }
""",
        "    fun attach(activity: Activity) { visible = WeakReference<Activity?>(activity) }\n",
        "Android remove request-helper visibility ownership",
    )
    replace(
        incoming,
        """    fun detach(activity: Activity) {
        if (visible.get() === activity) {
            visible.clear()
            LocalTransferEngine.setUiVisible(false)
        }
    }
""",
        "    fun detach(activity: Activity) { if (visible.get() === activity) visible.clear() }\n",
        "Android remove request-helper hidden ownership",
    )

    # Do not route accessibility clipboard events through a global callback as the
    # only handoff. Feed the process-level bridge directly. This keeps Android ->
    # desktop sending alive even when Activity/service lifecycle transitions race
    # with a copy event, while preserving the Shizuku watchdog as the privileged
    # fallback for Android 10+ background clipboard restrictions.
    replace(
        runtime,
        "    fun captureNow() { clipboard?.captureNowForForeground() }\n",
        """    fun captureNow() { clipboard?.captureNowForForeground() }
    fun captureAccessibility(clip: android.content.ClipData?) {
        clipboard?.captureNowForAccessibility(clip)
    }
""",
        "Android direct accessibility capture entry point",
    )
    replace(
        access,
        '''    private val clipboardListener = ClipboardManager.OnPrimaryClipChangedListener {
        // Read now: gallery/screenshot content URI grants belong to this system-bound
        // service and may no longer be readable by a later shell/Shizuku snapshot.
        val clip = runCatching { clipboard?.primaryClip }.getOrNull()
        BackgroundRuntime.start(this)
        val callback = ForegroundTracker.clipboardChanged
        if (callback != null) callback(clip) else BackgroundService.start(this, captureCurrent = true)
    }''',
        '''    private val clipboardListener = ClipboardManager.OnPrimaryClipChangedListener {
        // Read now while this system-bound service still owns any content URI grant,
        // then hand the event straight to the process runtime. The bridge can fall
        // back to Shizuku when Android does not expose ClipData here.
        val clip = runCatching { clipboard?.primaryClip }.getOrNull()
        BackgroundRuntime.start(this)
        BackgroundRuntime.captureAccessibility(clip)
    }''',
        "Android reliable accessibility clipboard handoff",
    )

    # File Transfer and Clipboard must agree about which LAN devices exist. UI
    # visibility is useful for choosing notification/dialog presentation, but it
    # must never hide a live file receiver from the recipient list. Receiver
    # readiness and TTL remain the availability gates.
    replace(
        engine,
        """        return nearby.values
            .filter { it.fingerprint != fingerprint(requireContext()) }
            .filter { it.visible || isFavorite(requireContext(), it.fingerprint) }
""",
        """        return nearby.values
            .filter { it.fingerprint != fingerprint(requireContext()) }
""",
        "Android show every live LAN file receiver",
    )

    final_runtime = runtime.read_text(encoding="utf-8")
    final_access = access.read_text(encoding="utf-8")
    final_engine = engine.read_text(encoding="utf-8")
    if "fun captureAccessibility(clip: android.content.ClipData?)" not in final_runtime:
        raise SystemExit("Android direct background capture entry point missing")
    if "BackgroundRuntime.captureAccessibility(clip)" not in final_access:
        raise SystemExit("Android accessibility direct handoff missing")
    if ".filter { it.visible || isFavorite(requireContext(), it.fingerprint) }" in final_engine:
        raise SystemExit("Android file-transfer visibility filter still present")

elif system == "Darwin":
    transfer = root / "ci/ClipMeshTransfer.swift"
    replace(
        transfer,
        """        return devices.values
            .filter { $0.fingerprint != TransferPrefs.fingerprint }
            .filter { visibleDevices.contains($0.fingerprint) || favorites.contains($0.fingerprint) }
""",
        """        return devices.values
            .filter { $0.fingerprint != TransferPrefs.fingerprint }
""",
        "macOS show every live LAN file receiver",
    )
    final_transfer = transfer.read_text(encoding="utf-8")
    if ".filter { visibleDevices.contains($0.fingerprint) || favorites.contains($0.fingerprint) }" in final_transfer:
        raise SystemExit("macOS file-transfer visibility filter still present")

elif system == "Windows":
    transfer = root / "ci/ClipMeshTransfer.cs"
    replace(
        transfer,
        """            values.RemoveAll(delegate(TransferDeviceC d) { return d.Fingerprint == Fingerprint; });
            values.RemoveAll(delegate(TransferDeviceC d) { return !IsFavorite(d.Fingerprint) && !visibleDevices.Contains(d.Fingerprint); });
""",
        """            values.RemoveAll(delegate(TransferDeviceC d) { return d.Fingerprint == Fingerprint; });
""",
        "Windows show every live LAN file receiver",
    )
    final_transfer = transfer.read_text(encoding="utf-8")
    if "!IsFavorite(d.Fingerprint) && !visibleDevices.Contains(d.Fingerprint)" in final_transfer:
        raise SystemExit("Windows file-transfer visibility filter still present")

else:
    raise SystemExit(f"unsupported platform {system}")

print(f"Applied ClipMesh process-presence, Android background-send, and unified transfer-discovery repair on {system}")