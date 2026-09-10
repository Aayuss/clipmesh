package dev.clipmesh.shizuku;

import dev.clipmesh.shizuku.IClipboardChangedCallback;

import android.os.IBinder;
import android.os.ParcelFileDescriptor;

interface IClipboardUserService {
    // Shizuku's reserved destroy transaction. Keep this exact explicit ID.
    void destroy() = 16777114;

    void init(in IBinder callerToken) = 1;
    String getPrimaryClipJson() = 2;
    boolean copyPrimaryClipItemToFile(int index, in ParcelFileDescriptor destination) = 3;
    String getLatestScreenshotJson() = 4;
    boolean copyUriToFile(String uri, in ParcelFileDescriptor destination) = 5;
    boolean setPrimaryClipText(String text) = 6;
    void setClipboardChangedCallback(IClipboardChangedCallback callback) = 7;
    boolean isClipboardListenerRegistered() = 8;
}
