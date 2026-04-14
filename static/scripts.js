function toggleConf() {
  var p = document.getElementById('conf-panel');
  var a = document.getElementById('conf-arrow');
  var o = p.style.display === 'block';
  p.style.display = o ? 'none' : 'block';
  a.style.transform = o ? '' : 'rotate(90deg)';
}

function toggleEpic(id) {
  var body = document.getElementById(id);
  var row  = body.previousElementSibling;
  var chev = row.querySelector('.chev');
  var open = body.style.display === 'block';
  body.style.display = open ? 'none' : 'block';
  if (chev) chev.classList.toggle('open', !open);
}

function toggleStory(id) {
  var detail = document.getElementById(id);
  var row    = detail.previousElementSibling;
  var chev   = row.querySelector('.chev');
  var open   = detail.style.display === 'block';
  detail.style.display = open ? 'none' : 'block';
  if (chev) chev.classList.toggle('open', !open);
}

function togglePanel(panelId, arrowId) {
  var p = document.getElementById(panelId);
  var a = document.getElementById(arrowId);
  var o = p.style.display === 'block';
  p.style.display = o ? 'none' : 'block';
  if (a) {
    a.style.transform = o ? '' : 'rotate(90deg)';
    a.textContent = o ? '▶' : '▼';
  }
}

function toggleReest() {
  var p = document.getElementById('reest-panel');
  var c = document.getElementById('reest-chev');
  var o = p.style.display === 'block';
  p.style.display = o ? 'none' : 'block';
  if (c) c.classList.toggle('open', !o);
}
