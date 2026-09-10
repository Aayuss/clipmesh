package dev.clipmesh

import android.app.Activity
import android.app.Dialog
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.ColorDrawable
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.text.InputType
import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView

/** ClipMesh-owned black/gold modal surface. The OS document picker remains
 * system-owned because Android's storage permission model requires it. */
object ClipMeshDialog {
    private val GOLD = 0xFFB58934.toInt()
    private val CARD = 0xFF111216.toInt()
    private val FIELD = 0xFF18191E.toInt()
    private val INK = 0xFFF4F1EA.toInt()
    private val MUTED = 0xFFA6A39C.toInt()

    fun info(activity: Activity, title: String, message: String, done: (() -> Unit)? = null) =
        show(activity, title, message, null, listOf("Done")) { done?.invoke() }

    fun confirm(activity: Activity, title: String, message: String, done: (Boolean) -> Unit) =
        show(activity, title, message, null, listOf("Cancel", "Continue")) { done(it == 1) }

    fun prompt(activity: Activity, title: String, message: String, initial: String = "", numeric: Boolean = false, multiline: Boolean = false, done: (String?) -> Unit) {
        val input = EditText(activity).apply {
            setText(initial); setTextColor(INK); setHintTextColor(MUTED); textSize = 15f
            inputType = if (numeric) InputType.TYPE_CLASS_NUMBER else InputType.TYPE_CLASS_TEXT
            if (multiline) { minLines = 2; maxLines = 5 } else setSingleLine(true)
            background = shape(FIELD, 12f, 0xFF34363E.toInt()); setPadding(dp(activity, 14), dp(activity, 11), dp(activity, 14), dp(activity, 11))
            if (initial.isNotEmpty()) setSelection(text.length)
        }
        show(activity, title, message, input, listOf("Cancel", "Continue")) { done(if (it == 1) input.text.toString() else null) }
    }

    fun choices(activity: Activity, title: String, choices: List<String>, done: (Int?) -> Unit) =
        show(activity, title, "", null, choices + "Cancel") { done(it.takeIf { index -> index in choices.indices }) }

    private fun show(activity: Activity, title: String, message: String, input: EditText?, actions: List<String>, done: (Int) -> Unit): Dialog {
        val dialog = Dialog(activity)
        val card = LinearLayout(activity).apply {
            orientation = LinearLayout.VERTICAL; setPadding(dp(activity, 22), dp(activity, 20), dp(activity, 22), dp(activity, 18)); background = shape(CARD, 22f, 0xFF34363E.toInt())
        }
        card.addView(TextView(activity).apply { text = title; textSize = 21f; setTextColor(INK); setTypeface(typeface, Typeface.BOLD) })
        if (message.isNotBlank()) card.addView(TextView(activity).apply { text = message; textSize = 14f; setTextColor(MUTED); setPadding(0, dp(activity, 9), 0, dp(activity, 12)) })
        if (input != null) card.addView(input, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { bottomMargin = dp(activity, 13) })
        val buttons = LinearLayout(activity).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.END }
        var completed = false
        actions.forEachIndexed { index, label ->
            buttons.addView(Button(activity).apply {
                text = label; isAllCaps = false; setTypeface(typeface, Typeface.BOLD); minHeight = dp(activity, 46)
                setTextColor(if (index == actions.lastIndex) Color.rgb(12, 12, 10) else INK)
                background = shape(if (index == actions.lastIndex) GOLD else FIELD, 16f, if (index == actions.lastIndex) GOLD else 0xFF34363E.toInt())
                setOnClickListener { performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP); completed = true; dialog.dismiss(); done(index) }
            }, LinearLayout.LayoutParams(0, dp(activity, 48), 1f).apply { if (index > 0) leftMargin = dp(activity, 8) })
        }
        card.addView(buttons, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(activity, 5) })
        dialog.setContentView(card); dialog.setCanceledOnTouchOutside(false)
        dialog.setOnCancelListener { if (!completed) { completed = true; done(-1) } }
        dialog.window?.apply {
            setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT)); addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND)
            attributes = attributes.apply { dimAmount = .72f; width = (activity.resources.displayMetrics.widthPixels * .88f).toInt() }
            if (Build.VERSION.SDK_INT >= 31) { addFlags(WindowManager.LayoutParams.FLAG_BLUR_BEHIND); attributes = attributes.apply { blurBehindRadius = dp(activity, 24) } }
        }
        dialog.show()
        dialog.window?.setLayout((activity.resources.displayMetrics.widthPixels * .88f).toInt(), ViewGroup.LayoutParams.WRAP_CONTENT)
        return dialog
    }

    private fun shape(fill: Int, radiusDp: Float, stroke: Int) = GradientDrawable().apply { shape = GradientDrawable.RECTANGLE; setColor(fill); cornerRadius = radiusDp * 3; setStroke(1, stroke) }
    private fun dp(activity: Activity, value: Int) = (value * activity.resources.displayMetrics.density).toInt()
}
