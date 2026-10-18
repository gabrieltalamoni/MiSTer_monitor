/* MiSTer Monitor library. SPDX-License-Identifier: AGPL-3.0-or-later */
'use strict';
const el = id => document.getElementById(id);
const state = {folder:'', page:1, pages:1, favorites:false, token:'', up:'', selected:null, busy:false};
let controller, searchTimer;
function message(text) { el('status').textContent = text; }
async function request(url, data, signal) {
  const response = await fetch(url, data ? {method:'POST', headers:{'Content-Type':'application/json'},body:JSON.stringify({...data,token:state.token}),signal} : {signal});
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `Erro HTTP ${response.status}`);
  return payload;
}
function card(item) {
  const button = document.createElement('button'); button.className='card';
  button.setAttribute('aria-label', (item.kind==='folder'?'Abrir pasta ':'Selecionar jogo ')+item.name);
  const art=document.createElement('div'); art.className='art';
  const placeholder=document.createElement('span');placeholder.className='placeholder';placeholder.textContent=item.kind==='folder'?'▦':'◈';art.append(placeholder);
  if(item.artwork) { const img=document.createElement('img'); img.alt=`Capa de ${item.name}`; img.loading='lazy'; img.src=item.artwork;
    img.onload=()=>{placeholder.hidden=true;}; img.onerror=()=>{img.remove();placeholder.textContent='Sem capa';placeholder.style.fontSize='18px';};art.append(img); }
  const caption=document.createElement('div');caption.className='caption';
  const title=document.createElement('div');title.className='title';title.textContent=item.name;
  const system=document.createElement('div');system.className='system';system.textContent=item.kind==='folder'?'ABRIR PASTA':item.system;
  caption.append(title,system);button.append(art,caption);
  if(item.favorite){const star=document.createElement('span');star.className='star';star.textContent='★';button.append(star);}
  button.onclick=()=>{if(state.busy)return;if(item.kind==='folder'){state.folder=item.path;state.page=1;state.favorites=false;el('search').value='';load();}else{state.selected=item;el('game-title').textContent=item.name;el('game-system').textContent=item.system;el('favorite').textContent=item.favorite?'★ Remover favorito':'☆ Favoritar';el('details').showModal();}};
  return button;
}
async function load(){
  if(controller) controller.abort();controller=new AbortController();
  const active=controller;
  message('Lendo jogos do microSD…');el('grid').replaceChildren();el('prev').disabled=el('next').disabled=true;
  const params=new URLSearchParams({folder:state.folder,page:state.page,per:12,q:el('search').value,favorites:state.favorites?'1':'0'});
  try{const result=await request('/library/page?'+params,undefined,active.signal);if(active!==controller)return;
    Object.assign(state,{page:result.page,pages:result.pages,token:result.token,up:result.up});
    el('folder').textContent=state.favorites?'Seus favoritos':state.folder.replace(/^\/media\/fat\//,'')||'Escolha um sistema';
    el('total').textContent=`${result.total} itens`;el('page').textContent=`${result.page} / ${result.pages}`;
    el('favorites').classList.toggle('active',state.favorites);el('home').classList.toggle('active',!state.folder&&!state.favorites);
    el('prev').disabled=state.page<=1;el('next').disabled=state.page>=state.pages;el('up').disabled=!state.folder||state.favorites;
    el('grid').replaceChildren(...result.items.map(card));
    if(!result.items.length){const empty=document.createElement('div');empty.className='empty';empty.textContent=state.favorites?'Seus favoritos aparecerão aqui. Selecione um jogo e toque em Favoritar.':'Nenhum jogo nesta pasta. Verifique o filtro e as pastas configuradas no MiSTer Remote.';el('grid').append(empty);}
    message('Escolha uma pasta ou toque na capa de um jogo. A busca filtra a pasta atual.');
  }catch(error){if(error.name==='AbortError')return;message(error.message);el('folder').textContent='Biblioteca indisponível';el('total').textContent='';el('page').textContent='';}
}
el('home').onclick=()=>{state.folder='';state.favorites=false;state.page=1;el('search').value='';load();};
el('favorites').onclick=()=>{state.favorites=true;state.page=1;el('search').value='';load();};
el('up').onclick=()=>{state.folder=state.up;state.page=1;el('search').value='';load();};
el('prev').onclick=()=>{state.page--;load();};el('next').onclick=()=>{state.page++;load();};el('refresh').onclick=load;
el('search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{state.page=1;load();},300);};
el('cancel').onclick=()=>el('details').close();
function busy(value){state.busy=value;el('launch').disabled=el('favorite').disabled=el('cancel').disabled=value;}
el('details').addEventListener('cancel',event=>{if(state.busy)event.preventDefault();});
el('favorite').onclick=async()=>{const item=state.selected;if(!item||state.busy)return;busy(true);
  try{const result=await request('/library/favorite',{id:item.id,enabled:!item.favorite});item.favorite=result.favorite;el('details').close();await load();message(result.favorite?'Jogo adicionado aos favoritos.':'Jogo removido dos favoritos.');}
  catch(error){message(error.message);el('details').close();}finally{busy(false);}};
el('launch').onclick=async()=>{const item=state.selected;if(!item||state.busy)return;busy(true);message('Solicitando lançamento…');
  try{await request('/library/launch',{id:item.id,confirmed:true});el('details').close();message(`Lançamento de ${item.name} solicitado ao MiSTer. Confira o jogo na TV.`);}
  catch(error){el('details').close();message(error.message);}finally{busy(false);}};
load();
