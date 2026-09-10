package dev.clipmesh

import android.app.Application
class ClipMeshApp : Application() {
    override fun onCreate() {
        super.onCreate()
        // The provider dependency initializes Shizuku. Keep application startup otherwise inert.
    }
}
