/* AgendaFlow SaaS — vanilla JS: ações reais, sem dependências de frontend */
(() => {
  'use strict';
  const $=(s,root=document)=>root.querySelector(s);
  const $$=(s,root=document)=>[...root.querySelectorAll(s)];
  const csrf=$('meta[name="csrf-token"]')?.content||'';
  let sending=false;
  function toast(msg,type='success'){
    const stack=$('#toast-stack');if(!stack)return;
    const div=document.createElement('div');div.className='toast '+type;div.textContent=msg;
    stack.appendChild(div);setTimeout(()=>div.remove(),5200);
  }
  async function api(url,method='GET',data){
    const options={method,credentials:'same-origin',headers:{'X-CSRF-Token':csrf}};
    if(data!==undefined){options.headers['Content-Type']='application/json';options.body=JSON.stringify(data)}
    let response;
    try{response=await fetch(url,options)}catch{throw new Error('Não foi possível acessar o servidor. Verifique sua conexão.')}
    let json={};try{json=await response.json()}catch{}
    if(!response.ok){
      const detail=typeof json.detail==='string'?json.detail:
        Array.isArray(json.detail)?json.detail.map(d=>d.msg).join('; '):`Falha na operação (HTTP ${response.status})`;
      throw new Error(detail);
    }
    return json;
  }
  async function run(fn){if(sending)return;sending=true;try{await fn()}catch(e){toast(e.message||'Não foi possível concluir a operação.','error')}finally{sending=false}}
  // Tema salvo por navegador; modo reduzido respeitado pelo CSS.
  try{document.documentElement.dataset.theme=localStorage.getItem('agendaflow-theme') || (matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light')}catch{document.documentElement.dataset.theme='light'}
  function setThemeLabels(){const dark=document.documentElement.dataset.theme==='dark';$$('[data-theme-toggle]').forEach(btn=>{btn.textContent=dark?'☼':'◐';btn.setAttribute('aria-label',dark?'Ativar modo claro':'Ativar modo escuro')})}
  setThemeLabels();$$('[data-theme-toggle]').forEach(btn=>btn.addEventListener('click',()=>{const next=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=next;try{localStorage.setItem('agendaflow-theme',next)}catch{}setThemeLabels()}));
  const progress=$('#top-progress');if(progress){window.addEventListener('scroll',()=>{const max=Math.max(1,document.documentElement.scrollHeight-innerHeight);progress.style.width=(window.scrollY/max*100)+'%'},{passive:true})}
  if('IntersectionObserver' in window && !matchMedia('(prefers-reduced-motion: reduce)').matches){document.body.classList.add('js-reveal');const observer=new IntersectionObserver(entries=>{for(const e of entries)if(e.isIntersecting){e.target.classList.add('visible');observer.unobserve(e.target)}},{threshold:.05,rootMargin:'0px 0px 80px 0px'});$$('.reveal').forEach(x=>observer.observe(x))}else{$$('.reveal').forEach(x=>x.classList.add('visible'))}
  const sidebar=$('#sidebar'),shade=$('#mobile-shade');$('[data-menu]')?.addEventListener('click',()=>{sidebar.classList.toggle('open');shade.hidden=!sidebar.classList.contains('open')});shade?.addEventListener('click',()=>{sidebar.classList.remove('open');shade.hidden=true});
  $$('[data-logout]').forEach(b=>b.addEventListener('click',()=>run(async()=>{const r=await api('/api/auth/logout','POST');location.assign(r.redirect)})));
  $$('[data-copy]').forEach(b=>b.addEventListener('click',()=>run(async()=>{const org=$('.workspace-container')?.dataset.slug;const value=org?`${location.origin}/r/${org}`:b.dataset.copy;try{await navigator.clipboard.writeText(value);toast('Link copiado para compartilhar.')}catch{toast('Seu navegador não permitiu copiar automaticamente.','error')}})));
  function parseForm(form){const out={};for(const [k,v] of new FormData(form)){if(k==='price_reais')out.price_cents=Math.round(Number(v)*100);else if(k==='weekday'||k==='slot_step'||k==='booking_window_days'||k==='min_notice_hours'||k==='cancel_notice_hours'||k==='duration_minutes'||k==='staff_id'||k==='service_id')out[k]=Number(v);else out[k]=v}
    for(const el of $$('input[type="checkbox"][name]',form))out[el.name]=el.checked;
    return out;
  }
  $$('form[data-api-form]').forEach(form=>form.addEventListener('submit',e=>{e.preventDefault();if(!form.reportValidity())return;run(async()=>{
    const button=form.querySelector('[type="submit"]');if(button)button.disabled=true;
    try{const url=form.dataset.apiForm;const res=await api(url,form.dataset.method||'POST',parseForm(form));toast(res.message||'Operação concluída.');
      if(res.redirect)location.assign(res.redirect);else if(form.dataset.reload==='true')location.reload();else if(form.closest('dialog'))form.closest('dialog').close();
    }finally{if(button)button.disabled=false}
  })}));
  $$('[data-modal]').forEach(button=>button.addEventListener('click',()=>{
    const dialog=document.getElementById(button.dataset.modal);if(!dialog)return;
    if(button.dataset.staffId){$('#hours-form [name="staff_id"]').value=button.dataset.staffId;$('#hours-heading').textContent='Horários · '+button.dataset.staffName}
    dialog.showModal();
  }));
  $$('[data-close]').forEach(b=>b.addEventListener('click',()=>b.closest('dialog')?.close()));
  $$('dialog').forEach(d=>d.addEventListener('click',e=>{if(e.target===d)d.close()}));
  $$('[data-edit-service]').forEach(button=>button.addEventListener('click',()=>{
    const d=$('#service-modal'),form=$('[data-entity-form="service"]',d);
    form.dataset.entityId=button.dataset.id;
    $('#service-modal-heading').textContent='Editar serviço';
    for(const [name,value] of Object.entries({name:button.dataset.name,category:button.dataset.category,description:button.dataset.description,duration_minutes:button.dataset.duration,price_reais:(Number(button.dataset.price)/100).toFixed(2)})){
      if(form.elements.namedItem(name))form.elements.namedItem(name).value=value;
    }
    form.elements.namedItem('active').checked=button.dataset.active==='true';d.showModal();
  }));
  $('[data-modal="service-modal"]')?.addEventListener('click',()=>{const f=$('[data-entity-form="service"]');delete f.dataset.entityId;f.reset();$('#service-modal-heading').textContent='Novo serviço'});
  $('[data-entity-form="service"]')?.addEventListener('submit',e=>{e.preventDefault();const form=e.currentTarget;if(!form.reportValidity())return;run(async()=>{
    const id=form.dataset.entityId;const url=form.dataset.route+(id?'/'+id:'');const method=id?'PATCH':'POST';
    const res=await api(url,method,parseForm(form));toast(res.message||'Serviço salvo.');location.reload();
  })});
  $('#hours-form')?.addEventListener('submit',e=>{e.preventDefault();run(async()=>{
    const values=parseForm(e.currentTarget),staffId=values.staff_id;delete values.staff_id;
    const slug=$('.workspace-container').dataset.slug;
    await api(`/api/org/${slug}/staff/${staffId}/hours`,'PUT',values);
    toast('Expediente atualizado.');$('#hours-modal').close();
  })});
  const bookingsSearch=$('#bookings-search'),statusFilter=$('#status-filter');
  function filterBookings(){const term=(bookingsSearch?.value||'').toLowerCase().trim();const status=statusFilter?.value||'';$$('#bookings-table tbody tr[data-search]').forEach(r=>r.hidden=!!((term&&!r.dataset.search.includes(term))||(status&&r.dataset.status!==status)))}
  bookingsSearch?.addEventListener('input',filterBookings);statusFilter?.addEventListener('change',filterBookings);
  $$('.status-select').forEach(sel=>sel.addEventListener('change',()=>run(async()=>{
    const status=sel.value;if(!status)return;
    if(status==='cancelled'&&!confirm('Cancelar este atendimento?')){sel.value='';return}
    const slug=$('.workspace-container').dataset.slug;
    await api(`/api/org/${slug}/bookings/${sel.dataset.bookingId}/status`,'PATCH',{status});toast('Status atualizado.');location.reload();
  })));
  $$('[data-anonymize]').forEach(button=>button.addEventListener('click',()=>run(async()=>{
    if(!confirm('Anonimizar permanentemente os dados pessoais deste cliente? Esta ação não pode ser desfeita.'))return;
    const slug=$('.workspace-container').dataset.slug;
    await api(`/api/org/${slug}/customers/${button.dataset.anonymize}`,'DELETE');toast('Dados anonimizados.');location.reload();
  })));
  $('#audit-button')?.addEventListener('click',()=>run(async()=>{
    const slug=$('.workspace-container').dataset.slug;const data=await api(`/api/org/${slug}/audit`);
    const list=$('#audit-list');list.hidden=false;list.replaceChildren();
    if(!data.items.length){list.textContent='Ainda não há atividades registradas.';return}
    for(const event of data.items){const row=document.createElement('div');
      const strong=document.createElement('strong'),small=document.createElement('small');
      strong.textContent=event.action+' · '+(event.details||'');small.textContent=' — '+new Date(event.occurred_at+'Z').toLocaleString('pt-BR');row.append(strong,small);list.append(row)}
  }));
  $$('[data-checkout]').forEach(b=>b.addEventListener('click',()=>run(async()=>{
    const slug=$('.workspace-container').dataset.slug;const res=await api(`/api/org/${slug}/billing/checkout`,'POST',{plan:b.dataset.checkout});location.assign(res.url);
  })));
  $('#billing-portal')?.addEventListener('click',()=>run(async()=>{
    const slug=$('.workspace-container').dataset.slug;const res=await api(`/api/org/${slug}/billing/portal`,'POST');location.assign(res.url);
  }));
  // Reserva pública: disponibilidade calculada no backend, sem simular horários.
  const bookingForm=$('#booking-form');
  if(bookingForm){
    let requestCounter=0;
    const selected=name=>bookingForm.querySelector(`input[name="${name}"]:checked`);
    const serviceEl=$('#summary-service'),staffEl=$('#summary-staff'),timeEl=$('#summary-time');
    function renderSummary(){const service=selected('service_id'),staff=selected('staff_id');serviceEl.textContent=service?.dataset.name||'A escolher';staffEl.textContent=staff?.dataset.name||'A escolher';timeEl.textContent=$('#selected-time').value||'A escolher';$('#booking-total').textContent=service?new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}).format(Number(service.dataset.price)/100):'Selecione um serviço'}
    async function loadSlots(){const service=selected('service_id'),staff=selected('staff_id'),day=$('#booking-date').value;const slots=$('#slots-grid'),message=$('#slot-message');
      const number=++requestCounter;slots.replaceChildren();$('#selected-time').value='';renderSummary();
      if(!service||!staff||!day){message.textContent='Escolha um serviço, um profissional e uma data.';return}
      message.textContent='Consultando disponibilidade real...';try{
        const q=new URLSearchParams({service_id:service.value,staff_id:staff.value,date:day});
        const data=await api(`/api/public/${bookingForm.dataset.slug}/availability?${q}`);
        if(number!==requestCounter)return;
        if(!data.slots.length){message.textContent='Sem horários nesta data. Experimente outro dia.';return}
        message.textContent='Escolha um dos horários disponíveis:';
        for(const time of data.slots){const b=document.createElement('button');b.className='slot';b.type='button';b.textContent=time;b.addEventListener('click',()=>{$$('.slot',slots).forEach(x=>x.classList.remove('selected'));b.classList.add('selected');$('#selected-time').value=time;renderSummary()});slots.appendChild(b)}
      }catch(e){if(number===requestCounter){message.textContent='Não foi possível carregar horários.';toast(e.message,'error')}}
    }
    $$('input[name="service_id"],input[name="staff_id"]',bookingForm).forEach(x=>x.addEventListener('change',loadSlots));$('#booking-date').addEventListener('change',loadSlots);
    bookingForm.addEventListener('submit',e=>{e.preventDefault();if(!bookingForm.reportValidity())return;if(!$('#selected-time').value){toast('Escolha um horário disponível.','error');return}
      run(async()=>{const button=bookingForm.querySelector('[type="submit"]');button.disabled=true;try{
        const data=parseForm(bookingForm);
        const res=await api(`/api/public/${bookingForm.dataset.slug}/book`,'POST',data);
        location.assign(res.manage_url);
      }finally{button.disabled=false}})
    });
    renderSummary();
  }
  // Link secreto de gerenciamento; altera somente a reserva associada.
  $('#manage-date')?.addEventListener('change',()=>run(async()=>{
    const select=$('#manage-time');select.replaceChildren();const date=$('#manage-date').value;
    if(!date)return;
    const token=$('#cancel-booking')?.dataset.token||$('.manage-form [name="token"]').value;
    const slots=await api(`/api/manage/${encodeURIComponent(token)}/availability?date=${date}`);
    for(const value of slots.slots){const opt=document.createElement('option');opt.value=value;opt.textContent=value;select.appendChild(opt)}
    if(!slots.slots.length){const opt=document.createElement('option');opt.value='';opt.textContent='Nenhum horário disponível';select.appendChild(opt)}
  }));
  $('#cancel-booking')?.addEventListener('click',e=>run(async()=>{
    if(!confirm('Cancelar seu agendamento?'))return;
    await api('/api/manage/cancel','POST',{token:e.currentTarget.dataset.token});toast('Agendamento cancelado.');location.reload();
  }));
})();
