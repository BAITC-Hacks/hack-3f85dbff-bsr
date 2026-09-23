const $ = (s) => document.querySelector(s);
const messages = $('#messages');
const form = $('#chatForm');
const input = $('#messageInput');
const sendBtn = $('#sendBtn');
const fileInput = $('#fileInput');
const filesBox = $('#files');
const cartPanel = $('#cartPanel');

const params = new URLSearchParams(location.search);
let sessionId = params.get('session') || localStorage.getItem('ekt_ai_session') || crypto.randomUUID();
localStorage.setItem('ekt_ai_session', sessionId);
let attachmentIds = [];

function esc(v=''){return String(v).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}
function money(v){return v==null?'—':new Intl.NumberFormat('ru-KZ').format(v)+' ₸';}
function qty(v){if(v==null)return 'не указано';const n=Number(v);return Number.isFinite(n)?new Intl.NumberFormat('ru-KZ',{maximumFractionDigits:2}).format(n):String(v);}

function productCard(p){
  const stockClass=p.stock!=null&&p.stock<=0?'stock-no':'stock-ok';
  const links=[];
  if(p.url) links.push(`<a href="${esc(p.url)}" target="_blank" rel="noopener">Карточка</a>`);
  if(p.certificate) links.push(`<a href="${esc(p.certificate)}" target="_blank" rel="noopener">Сертификат</a>`);
  const props=p.properties&&Object.keys(p.properties).length
    ? `<details><summary>Характеристики</summary><div class="props">${Object.entries(p.properties).slice(0,8).map(([k,v])=>`<span><b>${esc(k)}</b>${esc(v)}</span>`).join('')}</div></details>`:'';
  return `<article class="product">
    <div class="product-title">${esc(p.name)}</div>
    <div class="product-meta">
      <span>ID: ${esc(p.id)}</span>
      ${p.sku?`<span>Арт.: ${esc(p.sku)}</span>`:''}
      <span>${money(p.price)}</span>
      <span class="${stockClass}">Остаток: ${qty(p.stock ?? p.stock_text)}</span>
    </div>
    ${links.length?`<div class="product-links">${links.join('')}</div>`:''}
    ${props}
  </article>`;
}

function addMessage(text, who='bot', products=[], pending=null, cartUrl=null){
  const row=document.createElement('div'); row.className=`message ${who}`;
  let cards='';
  if(products?.length) cards='<div class="products">'+products.map(productCard).join('')+'</div>';
  let confirm='';
  if(pending){
    confirm=`<div class="confirm-row"><button class="yes" data-confirm="${esc(pending.pending_id)}">Да, добавить ${qty(pending.quantity)}</button><button class="no" data-cancel>Отмена</button></div>`;
  }
  const link=cartUrl?`<div class="confirm-row"><button class="yes" data-open-cart>Открыть корзину</button></div>`:'';
  row.innerHTML=`<div class="avatar">${who==='bot'?'AI':'Вы'}</div><div class="bubble"><div class="answer-text">${esc(text)}</div>${cards}${confirm}${link}</div>`;
  messages.appendChild(row); messages.scrollTop=messages.scrollHeight;
}

function showTyping(){
  const el=document.createElement('div'); el.id='typing'; el.className='message bot';
  el.innerHTML='<div class="avatar">AI</div><div class="bubble"><span class="typing"><i></i><i></i><i></i></span></div>';
  messages.appendChild(el); messages.scrollTop=messages.scrollHeight;
}
function hideTyping(){ $('#typing')?.remove(); }

async function api(path, options={}){
  const res=await fetch(path, options);
  let data={}; try{data=await res.json()}catch{}
  if(!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

async function sendPrompt(text){
  const clean=(text??input.value).trim();
  if(!clean && !attachmentIds.length) return;
  addMessage(clean || 'Отправлен файл', 'user');
  input.value=''; sendBtn.disabled=true; showTyping();
  try{
    const data=await api('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sessionId,message:clean,attachment_ids:attachmentIds})});
    hideTyping(); addMessage(data.answer,'bot',data.products,data.pending,data.cart_url);
    attachmentIds=[]; filesBox.innerHTML=''; await loadCart();
  }catch(err){hideTyping(); addMessage('Ошибка: '+err.message,'bot');}
  finally{sendBtn.disabled=false;input.focus();}
}

form.addEventListener('submit',e=>{e.preventDefault();sendPrompt();});

document.querySelectorAll('[data-prompt]').forEach(btn=>btn.addEventListener('click',()=>sendPrompt(btn.dataset.prompt)));

fileInput.addEventListener('change', async ()=>{
  const file=fileInput.files[0]; if(!file)return;
  const fd=new FormData(); fd.append('file',file);
  const chip=document.createElement('span'); chip.className='file-chip'; chip.textContent='Загрузка: '+file.name; filesBox.appendChild(chip);
  try{const data=await api('/api/upload',{method:'POST',body:fd}); attachmentIds.push(data.id); chip.textContent='✓ '+data.name;}
  catch(err){chip.textContent='Ошибка: '+err.message;}
  fileInput.value='';
});

messages.addEventListener('click',async e=>{
  const id=e.target.dataset.confirm;
  if(id){
    e.target.disabled=true;
    try{const data=await api('/api/cart/confirm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sessionId,pending_id:id})}); addMessage(data.message,'bot',[],null,data.cart.cart_url); await loadCart();}
    catch(err){addMessage('Не удалось добавить: '+err.message,'bot');}
    return;
  }
  if(e.target.dataset.cancel!==undefined){
    try{await api('/api/cart/cancel/'+encodeURIComponent(sessionId),{method:'POST'});}catch{}
    addMessage('Добавление отменено.','user'); return;
  }
  if(e.target.dataset.openCart!==undefined) openCart();
});

async function loadCart(){
  try{
    const data=await api('/api/cart/'+encodeURIComponent(sessionId));
    $('#cartCount').textContent=data.items.reduce((a,x)=>a+Number(x.quantity||0),0).toFixed(0);
    $('#cartItems').innerHTML=data.items.length?data.items.map(x=>`<div class="cart-item"><b>${esc(x.product.name)}</b><small>${qty(x.quantity)} × ${money(x.product.price)}${x.line_total!=null?' = '+money(x.line_total):''}</small></div>`).join(''):'<p>Корзина пуста.</p>';
    $('#cartTotal').textContent=data.total!=null?'Итого: '+money(data.total):'';
  }catch{}
}
function openCart(){cartPanel.classList.remove('hidden');loadCart();}
$('#cartBtn').addEventListener('click',openCart);
$('#closeCart').addEventListener('click',()=>cartPanel.classList.add('hidden'));
if(location.hash==='#cart') openCart(); else loadCart();
input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();form.requestSubmit();}});

(async()=>{
  try{await api('/health'); $('#apiStatus').classList.add('ok');}
  catch{$('#apiStatus').classList.add('bad');}
})();
