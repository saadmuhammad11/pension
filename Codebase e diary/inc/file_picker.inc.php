<?php
/**
 * One file picker for every form that takes a case's papers: many files, of many kinds, added a
 * few at a time.
 *
 * The plain <input type="file"> does two things a counter clerk trips over. Picking files a
 * second time REPLACES the first choice instead of adding to it, so a case scanned into three
 * files ends up with the last one only; and HESK's ticket form drew two single-file boxes, so a
 * case of five documents could not be attached at all. This keeps one list: every pick, and
 * every file dropped on it, is added; each file shows its kind and size and can be taken off
 * with its own button; a file of a kind or size the help desk will refuse is marked before the
 * form is sent, not after.
 *
 * The files travel in the one input, as name[] -- inc/attachments.inc.php renumbers them into
 * the attachment[1..N] the HESK upload loops read.
 */

if (!defined('IN_SCRIPT')) { die('Invalid attempt'); }

function hesk_file_picker($name, $types, $max_files, $max_bytes, $id = null)
{
	global $hesklang;
	static $styled = false;
	$id = $id ?: 'fp'.mt_rand(1000, 9999);
	$h = function ($s) { return htmlspecialchars((string) $s, ENT_QUOTES); };
	$out = '';
	if ( ! $styled)
	{
		$styled = true;
		$out .= '<style>
.fp { margin:6px 0 10px; }
.fp-drop { border:2px dashed #C7D2DA; border-radius:12px; padding:16px 18px; background:#F8FAFB; text-align:center;
    font-size:13px; color:#4B5563; transition:background .15s, border-color .15s; }
.fp-drop.is-over { background:#EDF4EE; border-color:#2D6A4F; }
.fp-drop .fp-choose { display:inline-block; margin:0 4px; padding:7px 16px; border-radius:999px; border:1px solid #2D6A4F;
    background:#fff; color:#1B4332; font-weight:700; cursor:pointer; font-size:13px; }
.fp-drop .fp-choose:hover { background:#EDF4EE; }
.fp-hint { display:block; margin-top:6px; font-size:12px; color:#6B7280; }
.fp-list { list-style:none; margin:10px 0 0; padding:0; }
.fp-list li { display:flex; align-items:center; gap:10px; padding:7px 10px; border:1px solid #E5E7EB; border-radius:8px;
    margin-bottom:6px; background:#fff; font-size:13px; }
.fp-kind { flex:0 0 auto; min-width:44px; text-align:center; font-size:10.5px; font-weight:800; letter-spacing:.3px;
    padding:3px 6px; border-radius:6px; background:#E4ECF7; color:#1E3A8A; }
.fp-kind--pdf { background:#FDE3E0; color:#8A1C12; } .fp-kind--img { background:#DDF1E4; color:#135C33; }
.fp-kind--doc { background:#E0E7FF; color:#3730A3; } .fp-kind--zip { background:#FCEBC8; color:#7A4F0F; }
.fp-name { flex:1 1 auto; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.fp-size { flex:0 0 auto; color:#6B7280; font-size:12px; }
.fp-bad { color:#B42318; font-weight:600; font-size:12px; }
.fp-rm { flex:0 0 auto; border:0; background:none; color:#6B7280; font-size:16px; line-height:1; cursor:pointer; padding:2px 6px; }
.fp-rm:hover { color:#B42318; }
.fp-count { font-size:12px; color:#374151; margin-top:4px; }
</style>';
	}
	$accept = implode(',', $types);
	$out .= '<div class="fp" id="'.$h($id).'" data-max="'.intval($max_files).'" data-maxbytes="'.intval($max_bytes).'"
    data-types="'.$h(json_encode(array_values($types))).'">
  <input type="file" name="'.$h($name).'[]" multiple accept="'.$h($accept).'" style="display:none">
  <div class="fp-drop">
    '.$hesklang['fp_drop'].' <button type="button" class="fp-choose">'.$hesklang['fp_choose'].'</button>
    <span class="fp-hint">'.sprintf($hesklang['fp_hint'], $h(implode(' ', $types)), round($max_bytes / 1048576).' MB', intval($max_files)).'</span>
  </div>
  <ul class="fp-list"></ul>
  <div class="fp-count"></div>
</div>
<script>
(function () {
  var root = document.getElementById('.json_encode($id).');
  var input = root.querySelector("input[type=file]"), list = root.querySelector(".fp-list");
  var drop = root.querySelector(".fp-drop"), count = root.querySelector(".fp-count");
  var max = +root.dataset.max, maxBytes = +root.dataset.maxbytes, types = JSON.parse(root.dataset.types);
  var T = '.json_encode(array('big' => $hesklang['fp_big'], 'type' => $hesklang['fp_type'], 'many' => $hesklang['fp_many'],
		'n' => $hesklang['fp_n'], 'rm' => $hesklang['fp_rm'])).';
  var kept = [];
  if (typeof DataTransfer === "undefined") { input.style.display = ""; drop.style.display = "none"; return; }

  function ext(f) { var m = f.name.match(/\\.[^.]+$/); return m ? m[0].toLowerCase() : ""; }
  function kind(e) {
    if (e === ".pdf") return ["PDF", "pdf"];
    if ([".jpg",".jpeg",".png",".tif",".tiff",".bmp",".gif",".webp"].indexOf(e) > -1) return [e.slice(1).toUpperCase(), "img"];
    if ([".doc",".docx",".odt",".rtf",".txt",".xls",".xlsx",".csv"].indexOf(e) > -1) return [e.slice(1).toUpperCase(), "doc"];
    if ([".zip",".rar"].indexOf(e) > -1) return [e.slice(1).toUpperCase(), "zip"];
    return [e ? e.slice(1).toUpperCase() : "?", ""];
  }
  function sync() {
    var dt = new DataTransfer();
    kept.forEach(function (f) { dt.items.add(f); });
    input.files = dt.files;
    render();
    root.dispatchEvent(new CustomEvent("fp-change", { bubbles: true, detail: { files: kept.slice() } }));
  }
  function add(files) {
    Array.prototype.forEach.call(files, function (f) {
      var dup = kept.some(function (k) { return k.name === f.name && k.size === f.size && k.lastModified === f.lastModified; });
      if (!dup) kept.push(f);
    });
    sync();
  }
  function render() {
    list.innerHTML = "";
    kept.forEach(function (f, i) {
      var li = document.createElement("li"), e = ext(f), k = kind(e);
      var b = document.createElement("span"); b.className = "fp-kind fp-kind--" + k[1]; b.textContent = k[0];
      var n = document.createElement("span"); n.className = "fp-name"; n.textContent = f.name; n.title = f.name;
      var s = document.createElement("span"); s.className = "fp-size"; s.textContent = (f.size / 1048576).toFixed(1) + " MB";
      li.appendChild(b); li.appendChild(n); li.appendChild(s);
      var problem = types.indexOf(e) < 0 ? T.type : (f.size > maxBytes ? T.big : (i >= max ? T.many : ""));
      if (problem) { var p = document.createElement("span"); p.className = "fp-bad"; p.textContent = problem; li.appendChild(p); }
      var r = document.createElement("button"); r.type = "button"; r.className = "fp-rm"; r.textContent = "✕";
      r.title = T.rm; r.setAttribute("aria-label", T.rm + " " + f.name);
      r.onclick = function () { kept.splice(i, 1); sync(); };
      li.appendChild(r); list.appendChild(li);
    });
    count.textContent = kept.length ? T.n.replace("%d", kept.length) : "";
  }
  root.querySelector(".fp-choose").onclick = function () { input.click(); };
  // A cancelled dialog empties the input in some browsers; the list is put back rather than lost.
  input.addEventListener("change", function () {
    if (input.files.length) add(Array.prototype.slice.call(input.files)); else sync();
  });
  ["dragenter", "dragover"].forEach(function (ev) { drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add("is-over"); }); });
  ["dragleave", "drop"].forEach(function (ev) { drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove("is-over"); }); });
  drop.addEventListener("drop", function (e) { if (e.dataTransfer && e.dataTransfer.files.length) add(e.dataTransfer.files); });
})();
</script>';
	return $out;
}
