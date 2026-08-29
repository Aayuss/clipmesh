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

print(f"Applied ClipMesh Android process-presence lifecycle repair on {system}")
