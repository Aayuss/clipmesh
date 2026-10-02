package dev.clipmesh.fileshare

import android.app.Activity
import android.app.Dialog
import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.os.Build
import android.view.Gravity
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.TextView
import dev.clipmesh.ClipMeshDialog
import dev.clipmesh.R
import java.lang.ref.WeakReference

/** Foreground Accept / Reject sheet for incoming files from a device that isn't starred. */
object IncomingRequestUi {
    @Volatile private var visible = WeakReference<Activity?>(null)
    fun attach(activity: Activity) { visible = WeakReference<Activity?>(activity) }
    fun detach(activity: Activity) { if (visible.get() === activity) visible.clear() }
    fun show(request: LocalTransferEngine.IncomingDecision): Boolean {
        val activity = visible.get()?.takeUnless { it.isFinishing || it.isDestroyed } ?: return false
        activity.runOnUiThread {
            val dialog = Dialog(activity)
            fun dp(v: Int) = ClipMeshDialog.dp(activity, v)
            val body = ClipMeshDialog.card(activity, bottomSheet = true)
            body.addView(TextView(activity).apply {
                text = "Incoming files"; textSize = 20f; setTextColor(Color.WHITE)
                typeface = ClipMeshDialog.font(activity, R.font.sora_semibold)
            })
            body.addView(TextView(activity).apply {
                text = "${request.senderAlias} wants to send you ${if (request.files.size == 1) "a file" else "${request.files.size} files"}"
                textSize = 14f; setTextColor(ClipMeshDialog.MUTED); typeface = ClipMeshDialog.font(activity, R.font.sora_regular)
                setPadding(0, dp(6), 0, dp(14))
            })
            val list = LinearLayout(activity).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(14), dp(10), dp(14), dp(10))
                background = android.graphics.drawable.GradientDrawable().apply {
                    setColor(ClipMeshDialog.FILL05); cornerRadius = dp(16).toFloat(); setStroke(dp(1), ClipMeshDialog.LINE)
                }
            }
            request.files.take(5).forEach { file ->
                list.addView(TextView(activity).apply {
                    text = file.fileName; textSize = 14f; setTextColor(Color.WHITE); maxLines = 1
                    ellipsize = android.text.TextUtils.TruncateAt.MIDDLE
                    typeface = ClipMeshDialog.font(activity, R.font.sora_medium); setPadding(0, dp(5), 0, dp(5))
                })
            }
            if (request.files.size > 5) list.addView(TextView(activity).apply {
                text = "+${request.files.size - 5} more"; textSize = 12f; setTextColor(ClipMeshDialog.MUTED); setPadding(0, dp(4), 0, dp(2))
            })
            body.addView(list)
            body.addView(TextView(activity).apply {
                text = "Trust this device (star it in Transfer) to skip this next time."
                textSize = 12f; setTextColor(ClipMeshDialog.MUTED); typeface = ClipMeshDialog.font(activity, R.font.sora_regular)
                setPadding(dp(2), dp(12), 0, 0)
            })
            var resolved = false
            fun resolve(accepted: Boolean) {
                if (resolved) return
                resolved = true
                LocalTransferEngine.resolveIncoming(request.requestId, accepted)
                ClipMeshDialog.dismissAnimated(dialog, body, toBottom = true)
            }
            val actions = LinearLayout(activity).apply { orientation = LinearLayout.HORIZONTAL }
            val reject = ClipMeshDialog.pill(activity, "Reject", ClipMeshDialog.Style.Secondary) { resolve(false) }
            val accept = ClipMeshDialog.pill(activity, "Accept", ClipMeshDialog.Style.Primary) { resolve(true) }
            actions.addView(reject, LinearLayout.LayoutParams(0, dp(50), 1f).apply { rightMargin = dp(6) })
            actions.addView(accept, LinearLayout.LayoutParams(0, dp(50), 1f).apply { leftMargin = dp(6) })
            body.addView(actions, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(20) })
            dialog.setContentView(body)
            dialog.setOnCancelListener { if (!resolved) { resolved = true; LocalTransferEngine.resolveIncoming(request.requestId, false) } }
            dialog.window?.apply {
                setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT))
                setGravity(Gravity.BOTTOM)
                addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND)
                attributes = attributes.apply { dimAmount = .55f }
                if (Build.VERSION.SDK_INT >= 31) { addFlags(WindowManager.LayoutParams.FLAG_BLUR_BEHIND); attributes = attributes.apply { blurBehindRadius = 28 } }
                setWindowAnimations(0)
                // Let the sheet run under the gesture bar instead of leaving a black strip.
                if (Build.VERSION.SDK_INT >= 30) {
                    setDecorFitsSystemWindows(false)
                    attributes = attributes.apply { fitInsetsTypes = 0 }
                    navigationBarColor = Color.TRANSPARENT
                    val basePadding = body.paddingBottom
                    body.setOnApplyWindowInsetsListener { v, insets ->
                        val nav = insets.getInsets(android.view.WindowInsets.Type.navigationBars()).bottom
                        v.setPadding(v.paddingLeft, v.paddingTop, v.paddingRight, basePadding + nav)
                        insets
                    }
                }
            }
            dialog.show()
            dialog.window?.setLayout(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
            ClipMeshDialog.animateIn(body, fromBottom = true)
        }
        return true
    }
}
