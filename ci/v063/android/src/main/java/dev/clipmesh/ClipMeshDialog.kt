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
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.view.animation.PathInterpolator
import android.view.inputmethod.InputMethodManager
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView

/**
 * ClipMesh "Ember" modal surfaces (Surface #222222, 22dp radius, pill buttons,
 * 260ms scale+fade entrance). View-based so any Activity, the share target and
 * background pairing prompts can raise them. The OS document picker stays
 * system-owned because Android's storage permission model requires it.
 */
object ClipMeshDialog {
    internal const val ACCENT = 0xFFE55F11.toInt()
    internal const val SURFACE = 0xFF222222.toInt()
    internal const val INK = 0xFFFFFFFF.toInt()
    internal const val MUTED = 0x80FFFFFF.toInt()
    internal const val LINE = 0x14FFFFFF
    internal const val FILL05 = 0x0DFFFFFF
    internal const val FILL07 = 0x12FFFFFF
    internal const val NEGATIVE = 0xFFFF6B5A.toInt()
    internal val EASE = PathInterpolator(0.2f, 0f, 0f, 1f)

    enum class Style { Primary, Secondary, Destructive }

    fun info(activity: Activity, title: String, message: String, done: (() -> Unit)? = null) =
        show(activity, title, message, null, listOf("Done" to Style.Primary)) { done?.invoke() }

    fun confirm(
        activity: Activity,
        title: String,
        message: String,
        confirmLabel: String = "Continue",
        destructive: Boolean = false,
        done: (Boolean) -> Unit,
    ) = show(activity, title, message, null, listOf("Cancel" to Style.Secondary, confirmLabel to if (destructive) Style.Destructive else Style.Primary)) { done(it == 1) }

    fun prompt(
        activity: Activity,
        title: String,
        message: String,
        initial: String = "",
        numeric: Boolean = false,
        multiline: Boolean = false,
        emphasized: Boolean = false,
        confirmLabel: String = "Continue",
        done: (String?) -> Unit,
    ) {
        val input = EditText(activity).apply {
            setText(initial); setTextColor(INK); setHintTextColor(if (emphasized) Color.argb(68, 166, 163, 156) else MUTED)
            textSize = if (emphasized) 34f else 15f
            typeface = if (emphasized) Typeface.MONOSPACE else font(activity, R.font.sora_regular)
            if (emphasized) { gravity = Gravity.CENTER; letterSpacing = .16f; hint = "000000" }
            inputType = if (numeric) InputType.TYPE_CLASS_NUMBER else InputType.TYPE_CLASS_TEXT or if (multiline) InputType.TYPE_TEXT_FLAG_MULTI_LINE else 0
            if (multiline) { minLines = 2; maxLines = 5 } else setSingleLine(true)
            background = field(activity, focused = false)
            setOnFocusChangeListener { v, has -> v.background = field(activity, has) }
            setPadding(dp(activity, 14), dp(activity, 12), dp(activity, 14), dp(activity, 12))
            if (initial.isNotEmpty()) setSelection(text.length)
        }
        val dialog = show(activity, title, message, input, listOf("Cancel" to Style.Secondary, confirmLabel to Style.Primary)) { done(if (it == 1) input.text.toString() else null) }
        input.requestFocus()
        input.postDelayed({
            (activity.getSystemService(Activity.INPUT_METHOD_SERVICE) as InputMethodManager).showSoftInput(input, 0)
        }, 160)
        dialog.window?.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE)
    }

    fun choices(activity: Activity, title: String, choices: List<String>, done: (Int?) -> Unit) =
        show(activity, title, "", null, choices.map { it to Style.Secondary } + ("Cancel" to Style.Secondary), vertical = true) {
            done(it.takeIf { index -> index in choices.indices })
        }

    /** Non-blocking verification-code surface; dismissed by the caller when pairing finishes. */
    fun code(activity: Activity, title: String, message: String, code: TextView, onDismiss: () -> Unit): Dialog {
        code.background = GradientDrawable().apply { setColor(FILL05); cornerRadius = dp(activity, 16).toFloat(); setStroke(dp(activity, 1), LINE) }
        code.setPadding(dp(activity, 8), dp(activity, 18), dp(activity, 8), dp(activity, 18))
        val waiting = TextView(activity).apply {
            text = "Waiting for confirmation…"; textSize = 12f; setTextColor(MUTED); typeface = font(activity, R.font.sora_medium)
            gravity = Gravity.CENTER; setPadding(0, dp(activity, 14), 0, 0)
            animate().alpha(.35f).setDuration(700).withEndAction(object : Runnable {
                override fun run() { animate().alpha(if (alpha < .5f) 1f else .35f).setDuration(700).withEndAction(this).start() }
            }).start()
        }
        val box = LinearLayout(activity).apply { orientation = LinearLayout.VERTICAL; addView(code); addView(waiting) }
        return show(activity, title, message, box, emptyList(), cancelable = true) { onDismiss() }
    }

    private fun show(
        activity: Activity,
        title: String,
        message: String,
        accessory: View?,
        actions: List<Pair<String, Style>>,
        vertical: Boolean = false,
        cancelable: Boolean = true,
        done: (Int) -> Unit,
    ): Dialog {
        val dialog = Dialog(activity)
        val card = card(activity)
        card.addView(TextView(activity).apply {
            text = title; textSize = 19f; setTextColor(INK); typeface = font(activity, R.font.sora_semibold)
        })
        if (message.isNotBlank()) card.addView(TextView(activity).apply {
            text = message; textSize = 14f; setTextColor(MUTED); typeface = font(activity, R.font.sora_regular)
            setLineSpacing(0f, 1.15f); setPadding(0, dp(activity, 8), 0, 0)
        })
        if (accessory != null) card.addView(accessory, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(activity, 16) })
        var completed = false
        fun finish(index: Int) {
            if (completed) return
            completed = true
            dismissAnimated(dialog, card)
            done(index)
        }
        if (actions.isNotEmpty()) {
            val buttons = LinearLayout(activity).apply {
                orientation = if (vertical) LinearLayout.VERTICAL else LinearLayout.HORIZONTAL
                gravity = Gravity.END
            }
            actions.forEachIndexed { index, (label, style) ->
                val pill = pill(activity, label, style) { finish(index) }
                buttons.addView(pill, if (vertical) {
                    LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(activity, 46)).apply { if (index > 0) topMargin = dp(activity, 8) }
                } else {
                    LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(activity, 44)).apply { if (index > 0) leftMargin = dp(activity, 8) }
                })
            }
            card.addView(buttons, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(activity, 22) })
        }
        dialog.setContentView(card)
        dialog.setCancelable(cancelable)
        dialog.setCanceledOnTouchOutside(cancelable && actions.size <= 1)
        dialog.setOnCancelListener { if (!completed) { completed = true; done(-1) } }
        dialog.window?.apply {
            setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT))
            addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND)
            attributes = attributes.apply { dimAmount = .55f }
            if (Build.VERSION.SDK_INT >= 31) { addFlags(WindowManager.LayoutParams.FLAG_BLUR_BEHIND); attributes = attributes.apply { blurBehindRadius = dp(activity, 18) } }
            setWindowAnimations(0)
        }
        dialog.show()
        val width = minOf((activity.resources.displayMetrics.widthPixels * .9f).toInt(), dp(activity, 440))
        dialog.window?.setLayout(width, ViewGroup.LayoutParams.WRAP_CONTENT)
        animateIn(card)
        return dialog
    }

    // -- Shared Ember view helpers (also used by IncomingRequestUi) -------------

    internal fun card(activity: Activity, bottomSheet: Boolean = false) = LinearLayout(activity).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(activity, 24), dp(activity, 22), dp(activity, 24), dp(activity, if (bottomSheet) 30 else 20))
        background = GradientDrawable().apply {
            setColor(SURFACE)
            val r = dp(activity, if (bottomSheet) 26 else 22).toFloat()
            cornerRadii = if (bottomSheet) floatArrayOf(r, r, r, r, 0f, 0f, 0f, 0f) else floatArrayOf(r, r, r, r, r, r, r, r)
            setStroke(dp(activity, 1), LINE)
        }
    }

    internal fun pill(activity: Activity, label: String, style: Style, onClick: () -> Unit) = TextView(activity).apply {
        text = label
        textSize = 14f
        typeface = font(activity, R.font.sora_semibold)
        gravity = Gravity.CENTER
        setPadding(dp(activity, 20), 0, dp(activity, 20), 0)
        minWidth = dp(activity, 92)
        setTextColor(if (style == Style.Destructive) NEGATIVE else INK)
        background = GradientDrawable().apply {
            cornerRadius = dp(activity, 30).toFloat()
            setColor(when (style) { Style.Primary -> ACCENT; Style.Secondary -> FILL07; Style.Destructive -> 0x29FF6B5A })
        }
        isClickable = true
        setOnTouchListener { v, event ->
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> v.animate().scaleX(.96f).scaleY(.96f).setDuration(100).setInterpolator(EASE).start()
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> v.animate().scaleX(1f).scaleY(1f).setDuration(160).setInterpolator(EASE).start()
            }
            false
        }
        setOnClickListener { performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP); onClick() }
    }

    internal fun animateIn(card: View, fromBottom: Boolean = false) {
        card.alpha = 0f
        if (fromBottom) card.translationY = card.resources.displayMetrics.density * 48 else { card.scaleX = .94f; card.scaleY = .94f }
        card.animate().alpha(1f).scaleX(1f).scaleY(1f).translationY(0f).setDuration(260).setInterpolator(EASE).start()
    }

    internal fun dismissAnimated(dialog: Dialog, card: View, toBottom: Boolean = false) {
        card.animate().alpha(0f).apply {
            if (toBottom) translationY(card.resources.displayMetrics.density * 40) else { scaleX(.96f); scaleY(.96f) }
        }.setDuration(180).setInterpolator(EASE).withEndAction { runCatching { dialog.dismiss() } }.start()
    }

    internal fun font(activity: Activity, id: Int): Typeface = runCatching { activity.resources.getFont(id) }.getOrDefault(Typeface.DEFAULT)

    private fun field(activity: Activity, focused: Boolean) = GradientDrawable().apply {
        setColor(FILL05); cornerRadius = dp(activity, 14).toFloat(); setStroke(dp(activity, 1), if (focused) ACCENT else LINE)
    }

    internal fun dp(activity: Activity, value: Int) = (value * activity.resources.displayMetrics.density + .5f).toInt()
}
