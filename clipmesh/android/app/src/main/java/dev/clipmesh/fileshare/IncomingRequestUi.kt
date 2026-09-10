package dev.clipmesh.fileshare

import android.app.Activity
import android.app.Dialog
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.view.Gravity
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import java.lang.ref.WeakReference

object IncomingRequestUi {
    @Volatile private var visible = WeakReference<Activity?>(null)
    fun attach(activity: Activity) { visible = WeakReference<Activity?>(activity) }
    fun detach(activity: Activity) { if (visible.get() === activity) visible.clear() }
    fun show(request: LocalTransferEngine.IncomingDecision): Boolean {
        val activity = visible.get()?.takeUnless { it.isFinishing || it.isDestroyed } ?: return false
        activity.runOnUiThread {
            val dialog = Dialog(activity)
            val density = activity.resources.displayMetrics.density
            fun dp(v:Int)=(v*density+.5f).toInt()
            val body = LinearLayout(activity).apply {
                orientation=LinearLayout.VERTICAL; setPadding(dp(24),dp(24),dp(24),dp(28))
                background=GradientDrawable().apply { setColor(Color.rgb(17,18,22)); cornerRadii=floatArrayOf(dp(26).toFloat(),dp(26).toFloat(),dp(26).toFloat(),dp(26).toFloat(),0f,0f,0f,0f) }
            }
            body.addView(TextView(activity).apply { text="Incoming files"; textSize=23f; setTextColor(Color.WHITE) })
            val names=request.files.take(5).joinToString("\n") { "• ${it.fileName}" } + if(request.files.size>5) "\n• +${request.files.size-5} more" else ""
            body.addView(TextView(activity).apply { text="${request.senderAlias} is trying to send:\n\n$names"; textSize=15f; setTextColor(Color.rgb(205,205,201)); setPadding(0,dp(12),0,dp(20)) })
            val actions=LinearLayout(activity).apply { orientation=LinearLayout.HORIZONTAL }
            val reject=Button(activity).apply { text="Reject"; isAllCaps=false; setOnClickListener { LocalTransferEngine.resolveIncoming(request.requestId,false); dialog.dismiss() } }
            val accept=Button(activity).apply { text="Accept"; isAllCaps=false; setOnClickListener { LocalTransferEngine.resolveIncoming(request.requestId,true); dialog.dismiss() } }
            actions.addView(reject,LinearLayout.LayoutParams(0,dp(52),1f).apply{rightMargin=dp(6)}); actions.addView(accept,LinearLayout.LayoutParams(0,dp(52),1f).apply{leftMargin=dp(6)}); body.addView(actions)
            dialog.setContentView(body); dialog.setOnCancelListener { LocalTransferEngine.resolveIncoming(request.requestId,false) }
            dialog.window?.apply { setBackgroundDrawableResource(android.R.color.transparent); setLayout(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT); setGravity(Gravity.BOTTOM); addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND); attributes=attributes.apply{dimAmount=.72f}; if(Build.VERSION.SDK_INT>=31){addFlags(WindowManager.LayoutParams.FLAG_BLUR_BEHIND); attributes=attributes.apply{blurBehindRadius=28}} }
            dialog.show(); dialog.window?.setLayout(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT)
        }
        return true
    }
}
