/* =========================================================
   dashboard/static/js/main.js
   Deal Hunter Bot — Shared JavaScript Utilities
   ========================================================= */

'use strict';

/* ── 1. Flash message auto-dismiss ────────────────────── */
(function () {
    function initFlashDismiss() {
        const flashes = document.querySelectorAll('.flash-success, .flash-error, .flash-warning');
        flashes.forEach(function (el) {
            // auto remove after 4 seconds
            setTimeout(function () {
                el.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
                el.style.opacity = '0';
                el.style.transform = 'translateY(-6px)';
                setTimeout(function () { el.remove(); }, 420);
            }, 4000);
        });
    }
    document.addEventListener('DOMContentLoaded', initFlashDismiss);
})();


/* ── 2. Confirm delete helper ──────────────────────────── */
function confirmDelete(message) {
    return window.confirm(message || 'Are you sure? This cannot be undone.');
}


/* ── 3. Modal helpers ───────────────────────────────────── */
function openModal(id) {
    var el = document.getElementById(id);
    if (!el) return;
    el.classList.remove('hidden');
    el.classList.add('flex');
    el.classList.add('fade-in');
    // close on backdrop click
    el.addEventListener('click', function handler(e) {
        if (e.target === el) {
            closeModal(id);
            el.removeEventListener('click', handler);
        }
    });
    // close on Escape
    document.addEventListener('keydown', function escHandler(e) {
        if (e.key === 'Escape') {
            closeModal(id);
            document.removeEventListener('keydown', escHandler);
        }
    });
}

function closeModal(id) {
    var el = document.getElementById(id);
    if (!el) return;
    el.style.opacity = '0';
    el.style.transition = 'opacity 0.2s ease';
    setTimeout(function () {
        el.classList.add('hidden');
        el.classList.remove('flex');
        el.style.opacity = '';
        el.style.transition = '';
    }, 200);
}


/* ── 4. Password visibility toggle ─────────────────────── */
function togglePasswordVisibility(inputId, iconId) {
    var input = document.getElementById(inputId);
    var icon = document.getElementById(iconId);
    if (!input || !icon) return;
    if (input.type === 'password') {
        input.type = 'text';
        icon.textContent = 'visibility';
    } else {
        input.type = 'password';
        icon.textContent = 'visibility_off';
    }
}


/* ── 5. Inline edit toggle (categories page) ────────────── */
function showEdit(id) {
    var view = document.getElementById('view-' + id);
    var edit = document.getElementById('edit-' + id);
    if (view) view.classList.add('hidden');
    if (edit) edit.classList.remove('hidden');
}

function hideEdit(id) {
    var edit = document.getElementById('edit-' + id);
    var view = document.getElementById('view-' + id);
    if (edit) edit.classList.add('hidden');
    if (view) view.classList.remove('hidden');
}


/* ── 6. Slug auto-generator (admins create form) ───────── */
function autoSlug(sourceId, targetId) {
    var source = document.getElementById(sourceId);
    var target = document.getElementById(targetId);
    if (!source || !target) return;
    source.addEventListener('input', function () {
        target.value = source.value
            .toLowerCase()
            .trim()
            .replace(/[^a-z0-9\s-]/g, '')
            .replace(/\s+/g, '-')
            .replace(/-+/g, '-');
    });
}


/* ── 7. Copy to clipboard ──────────────────────────────── */
function copyToClipboard(text, buttonEl) {
    navigator.clipboard.writeText(text).then(function () {
        if (!buttonEl) return;
        var original = buttonEl.innerHTML;
        buttonEl.innerHTML = '<span class="material-symbols-outlined text-[14px]">check</span> Copied!';
        buttonEl.classList.add('text-emerald-400');
        setTimeout(function () {
            buttonEl.innerHTML = original;
            buttonEl.classList.remove('text-emerald-400');
        }, 1800);
    });
}


/* ── 8. Live Console (SSE log stream) ───────────────────── */
var DealConsole = (function () {
    var paused = false;
    var lineCount = 0;
    var MAX_LINES = 600;
    var output = null;
    var statusEl = null;
    var evtSource = null;

    function colorLine(text) {
        if (/❌|error|traceback/i.test(text)) return 'log-error';
        if (/✅|🚨|sent|success/i.test(text)) return 'log-success';
        if (/⚠️|warning|warn/i.test(text)) return 'log-warning';
        if (/🔍|⚡|🎯|🌍|🤖|info/i.test(text)) return 'log-info';
        return 'log-default';
    }

    function appendLine(text) {
        if (paused || !output) return;
        var line = document.createElement('div');
        line.className = 'log-line ' + colorLine(text);
        line.textContent = text;
        output.appendChild(line);
        lineCount++;
        if (lineCount > MAX_LINES) {
            output.removeChild(output.firstChild);
            lineCount--;
        }
        var box = document.getElementById('console-box');
        if (box) box.scrollTop = box.scrollHeight;
    }

    function init(logUrl, outputId, statusId) {
        output = document.getElementById(outputId);
        statusEl = document.getElementById(statusId);

        evtSource = new EventSource(logUrl);
        evtSource.onopen = function () {
            if (statusEl) {
                statusEl.textContent = 'Connected — streaming live';
                statusEl.className = 'text-sm text-emerald-400';
            }
        };
        evtSource.onmessage = function (e) {
            try { appendLine(JSON.parse(e.data)); }
            catch (_) { appendLine(e.data); }
        };
        evtSource.onerror = function () {
            if (statusEl) {
                statusEl.textContent = 'Reconnecting…';
                statusEl.className = 'text-sm text-amber-400';
            }
        };
    }

    function togglePause(btnEl) {
        paused = !paused;
        if (btnEl) {
            btnEl.innerHTML = paused
                ? '<span class="material-symbols-outlined text-[16px]">play_arrow</span> Resume'
                : '<span class="material-symbols-outlined text-[16px]">pause</span> Pause';
        }
        if (statusEl) {
            statusEl.textContent = paused ? 'Paused' : 'Connected — streaming live';
        }
    }

    function clearLog() {
        if (output) output.innerHTML = '';
        lineCount = 0;
    }

    return { init: init, togglePause: togglePause, clearLog: clearLog };
})();


/* ── 9. Table search filter ─────────────────────────────── */
function initTableSearch(inputId, tableBodyId) {
    var input = document.getElementById(inputId);
    var tbody = document.getElementById(tableBodyId);
    if (!input || !tbody) return;
    input.addEventListener('input', function () {
        var query = input.value.toLowerCase();
        var rows = tbody.querySelectorAll('tr');
        rows.forEach(function (row) {
            row.style.display = row.textContent.toLowerCase().includes(query) ? '' : 'none';
        });
    });
}


/* ── 10. Prevent double-submit on forms ─────────────────── */
(function () {
    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('form').forEach(function (form) {
            form.addEventListener('submit', function () {
                var btn = form.querySelector('button[type="submit"]');
                if (btn) {
                    setTimeout(function () {
                        btn.disabled = true;
                        btn.style.opacity = '0.6';
                        btn.style.cursor = 'not-allowed';
                    }, 50);
                }
            });
        });
    });
})();