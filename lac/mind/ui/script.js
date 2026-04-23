let ws = null
let models = []
let debating = false
let currentChatId = null
let currentThinkingContent = null

const urlPath = window.location.pathname
const chatMatch = urlPath.match(/^\/chat\/(.+)$/)
if (chatMatch) {
  currentChatId = chatMatch[1]
  loadExistingChat(currentChatId)
}

async function loadExistingChat(chatId) {
  const res = await fetch(`/api/chat/${chatId}`)
  const data = await res.json()
  if (data.ok && data.debate) {
    document.getElementById('centered-input').classList.add('hidden')
    document.getElementById('chat-mode').classList.remove('hidden')
    
    const debate = data.debate
    
    // Split prompts and consensus by separator
    const prompts = debate.prompt.split('\n\n---\n\n')
    const consensuses = debate.consensus.split('\n\n---\n\n')
    
    // Display all Q&A pairs
    for (let i = 0; i < prompts.length; i++) {
      addUserMessage(prompts[i])
      
      if (consensuses[i]) {
        const container = document.getElementById('chat-container')
        const uniqueId = 'msg-loaded-' + i
        const msg = document.createElement('div')
        msg.innerHTML = `
          <div class="flex items-start gap-3">
            <div class="w-8 h-8 rounded-full bg-[#16aefe] flex items-center justify-center flex-shrink-0 mt-1">
              <i class="fa-solid fa-brain text-black text-sm"></i>
            </div>
            <div class="flex-1 min-w-0 space-y-3">
              <div class="thinking-container rounded-2xl overflow-hidden">
                <button onclick="toggleThinkingById('${uniqueId}')" class="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-[#222] transition-colors">
                  <div class="flex items-center gap-2">
                    <i id="thinking-icon-${uniqueId}" class="fa-solid fa-chevron-down text-[#666] text-xs"></i>
                    <span class="text-sm text-[#999]">Thinking</span>
                  </div>
                  <span class="text-xs text-[#666]">complete</span>
                </button>
                <div id="thinking-content-${uniqueId}" class="thinking-content-scroll px-4 pb-3 space-y-2 hidden">
                  ${debate.transcript.map(t => `
                    <div class="thinking-entry pl-3 py-2">
                      <div class="text-xs text-[#666] mb-1 font-medium">${escapeHtml(t.model_name || '')}</div>
                      <div class="thinking-text">${escapeHtml(t.content || '')}</div>
                    </div>
                  `).join('')}
                </div>
              </div>
              <div class="answer-container relative group">
                <button onclick="copyAnswerById('${uniqueId}')" class="copy-btn absolute top-2 right-2 px-2 py-1.5 bg-[#2a2a2a] hover:bg-[#333] text-[#999] hover:text-white text-xs rounded-lg transition-all flex items-center gap-1.5">
                  <i id="copy-icon-${uniqueId}" class="fa-regular fa-copy"></i>
                  <span id="copy-text-${uniqueId}">Copy</span>
                </button>
                <div id="final-answer-${uniqueId}" class="answer-text" data-raw="${escapeHtml(consensuses[i])}">${marked.parse(consensuses[i])}</div>
              </div>
            </div>
          </div>
        `
        container.appendChild(msg)
      }
    }
    
    document.getElementById('export-btn').disabled = false
    document.getElementById('export-btn').classList.remove('text-[#333]')
    document.getElementById('export-btn').classList.add('text-[#666]')
    scrollToBottom()
  }
}

async function loadModels() {
  const res = await fetch('/api/models')
  models = await res.json()
  if (models.length < 2) {
    window.location.href = '/setup'
    return
  }
  renderModelPills()
}

function renderModelPills() {
  const html = models.map(m => `
    <label class="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs text-[#999] bg-[#2f2f2f] cursor-pointer hover:bg-[#3a3a3a] transition-colors">
      <input type="checkbox" value="${m.name}" checked class="w-3.5 h-3.5 accent-accent model-checkbox" />
      ${m.name}
    </label>
  `).join('')
  document.getElementById('model-pills').innerHTML = html
  document.getElementById('model-pills-bottom').innerHTML = html
}

function handleDurationChange() {
  const select = document.getElementById('duration-select')
  const selectBottom = document.getElementById('duration-select-bottom')
  const customInput = document.getElementById('custom-duration')
  const customInputBottom = document.getElementById('custom-duration-bottom')
  
  // Sync both selects
  selectBottom.value = select.value
  
  if (select.value === 'custom') {
    customInput.classList.remove('hidden')
    customInputBottom.classList.remove('hidden')
    customInput.focus()
  } else {
    customInput.classList.add('hidden')
    customInputBottom.classList.add('hidden')
  }
}

function handleDurationChangeBottom() {
  const select = document.getElementById('duration-select')
  const selectBottom = document.getElementById('duration-select-bottom')
  const customInput = document.getElementById('custom-duration')
  const customInputBottom = document.getElementById('custom-duration-bottom')
  
  // Sync both selects
  select.value = selectBottom.value
  
  if (selectBottom.value === 'custom') {
    customInput.classList.remove('hidden')
    customInputBottom.classList.remove('hidden')
    customInputBottom.focus()
  } else {
    customInput.classList.add('hidden')
    customInputBottom.classList.add('hidden')
  }
}

function getSelectedModels() {
  return [...document.querySelectorAll('.model-checkbox:checked')].map(i => i.value)
}

function autoResize(el) {
  el.style.height = 'auto'
  el.style.height = el.scrollHeight + 'px'
}

function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}

function handleKeyBottom(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessageBottom()
  }
}

function sendMessage() {
  if (debating) return
  const prompt = document.getElementById('prompt-input-center').value.trim()
  if (!prompt) return

  const selected = getSelectedModels()
  if (selected.length < 2) return showError('Select at least 2 models')

  document.getElementById('centered-input').classList.add('hidden')
  document.getElementById('chat-mode').classList.remove('hidden')
  
  if (!currentChatId) {
    currentChatId = Date.now().toString(36) + Math.random().toString(36).substr(2, 5)
    history.pushState({}, '', `/chat/${currentChatId}`)
  }

  addUserMessage(prompt)
  document.getElementById('prompt-input-center').value = ''
  document.getElementById('prompt-input-center').style.height = 'auto'
  debating = true
  document.getElementById('send-btn').disabled = true
  document.getElementById('send-btn-center').disabled = true
  addAssistantMessage()
  connectWS(prompt, selected)
}

function sendMessageBottom() {
  if (debating) return
  const prompt = document.getElementById('prompt-input').value.trim()
  if (!prompt) return

  const selected = getSelectedModels()
  if (selected.length < 2) return showError('Select at least 2 models')

  addUserMessage(prompt)
  document.getElementById('prompt-input').value = ''
  document.getElementById('prompt-input').style.height = 'auto'
  debating = true
  document.getElementById('send-btn').disabled = true
  document.getElementById('send-btn-center').disabled = true
  addAssistantMessage()
  connectWS(prompt, selected)
}

function addUserMessage(text) {
  const container = document.getElementById('chat-container')
  const msg = document.createElement('div')
  msg.className = 'flex justify-end'
  msg.innerHTML = `
    <div class="message-user rounded-3xl px-5 py-3 max-w-xl">
      <div class="answer-text">${escapeHtml(text)}</div>
    </div>
  `
  container.appendChild(msg)
  document.getElementById('export-btn').disabled = false
  document.getElementById('export-btn').classList.remove('text-[#333]')
  document.getElementById('export-btn').classList.add('text-[#666]')
  scrollToBottom()
}

function addAssistantMessage() {
  const container = document.getElementById('chat-container')
  const msg = document.createElement('div')
  const uniqueId = 'msg-' + Date.now()
  msg.innerHTML = `
    <div class="flex items-start gap-3">
      <div class="w-8 h-8 rounded-full bg-[#16aefe] flex items-center justify-center flex-shrink-0 mt-1">
        <i class="fa-solid fa-brain text-black text-sm"></i>
      </div>
      <div class="flex-1 min-w-0 space-y-3">
        <div class="thinking-container rounded-2xl overflow-hidden">
          <button onclick="toggleThinkingById('${uniqueId}')" class="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-[#222] transition-colors">
            <div class="flex items-center gap-2">
              <i id="thinking-icon-${uniqueId}" class="fa-solid fa-chevron-down text-[#666] text-xs"></i>
              <span class="text-sm text-[#999]">Thinking</span>
            </div>
            <span id="thinking-status-${uniqueId}" class="text-xs text-[#666]">in progress...</span>
          </button>
          <div id="thinking-content-${uniqueId}" class="thinking-content-scroll px-4 pb-3 space-y-2"></div>
          <div id="stop-thinking-container-${uniqueId}" class="hidden px-4 pb-3">
            <button onclick="stopThinking()" class="w-full px-3 py-2 bg-[#2a2a2a] hover:bg-[#333] text-[#999] hover:text-white text-xs rounded-lg transition-colors flex items-center justify-center gap-2">
              <i class="fa-solid fa-stop"></i>
              <span>Stop & Finalize</span>
            </button>
          </div>
        </div>
        <div class="answer-container relative group">
          <button onclick="copyAnswerById('${uniqueId}')" class="copy-btn absolute top-2 right-2 px-2 py-1.5 bg-[#2a2a2a] hover:bg-[#333] text-[#999] hover:text-white text-xs rounded-lg transition-all flex items-center gap-1.5">
            <i id="copy-icon-${uniqueId}" class="fa-regular fa-copy"></i>
            <span id="copy-text-${uniqueId}">Copy</span>
          </button>
          <div id="final-answer-${uniqueId}" class="answer-text"></div>
        </div>
      </div>
    </div>
  `
  container.appendChild(msg)
  currentThinkingContent = document.getElementById(`thinking-content-${uniqueId}`)
  window.currentMessageId = uniqueId
  scrollToBottom()
}

function toggleThinkingById(id) {
  const content = document.getElementById(`thinking-content-${id}`)
  const icon = document.getElementById(`thinking-icon-${id}`)
  if (!content || !icon) return
  const isHidden = content.classList.contains('hidden')
  if (isHidden) {
    content.classList.remove('hidden')
    icon.classList.replace('fa-chevron-right', 'fa-chevron-down')
  } else {
    content.classList.add('hidden')
    icon.classList.replace('fa-chevron-down', 'fa-chevron-right')
  }
}

function toggleThinking() {
  const content = document.getElementById('thinking-content')
  const icon = document.getElementById('thinking-icon')
  if (!content || !icon) return
  const isHidden = content.classList.contains('hidden')
  if (isHidden) {
    content.classList.remove('hidden')
    icon.classList.replace('fa-chevron-right', 'fa-chevron-down')
  } else {
    content.classList.add('hidden')
    icon.classList.replace('fa-chevron-down', 'fa-chevron-right')
  }
}

function connectWS(prompt, selected) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  ws = new WebSocket(`${proto}://${location.host}/ws/debate`)

  ws.onopen = () => {
    const durationSelect = document.getElementById('duration-select')
    const durationSelectBottom = document.getElementById('duration-select-bottom')
    let duration = parseInt(durationSelect.value)
    if (durationSelect.value === 'custom') {
      const customMinutes = parseInt(document.getElementById('custom-duration').value)
      if (customMinutes && customMinutes > 0) duration = customMinutes * 60
      else duration = 120
    }
    
    // Sync both selects
    durationSelectBottom.value = durationSelect.value
    
    const history = []
    const container = document.getElementById('chat-container')
    const messages = container.querySelectorAll(':scope > div')
    
    // Only include the last Q&A pair to avoid overwhelming context
    let lastQuestion = ''
    let lastAnswer = ''
    
    for (let i = messages.length - 1; i >= 0; i--) {
      const msg = messages[i]
      if (!msg.classList.contains('justify-end') && !lastAnswer) {
        const answerEl = msg.querySelector('[id^="final-answer-"]')
        lastAnswer = answerEl?.dataset.raw || answerEl?.textContent || ''
      } else if (msg.classList.contains('justify-end') && !lastQuestion) {
        lastQuestion = msg.querySelector('.answer-text')?.textContent || ''
        if (lastAnswer) break
      }
    }
    
    if (lastQuestion && lastAnswer) {
      history.push({ question: lastQuestion, answer: lastAnswer })
    }
    
    ws.send(JSON.stringify({ prompt, duration, models: selected, chat_id: currentChatId, history }))
  }

  ws.onmessage = (e) => handleMessage(JSON.parse(e.data))
  ws.onerror = (err) => {
    console.error('WebSocket error:', err)
    showError('Connection lost')
    debating = false
    document.getElementById('send-btn').disabled = false
    document.getElementById('send-btn-center').disabled = false
  }
  ws.onclose = () => {
    console.log('WebSocket closed')
    debating = false
    document.getElementById('send-btn').disabled = false
    document.getElementById('send-btn-center').disabled = false
  }
}

function handleMessage(msg) {
  switch (msg.type) {
    case 'error': 
      showError(msg.message)
      debating = false
      document.getElementById('send-btn').disabled = false
      document.getElementById('send-btn-center').disabled = false
      updateThinkingStatusCurrent('error')
      break
    case 'debate_start': 
      const stopContainer = document.getElementById(`stop-thinking-container-${window.currentMessageId}`)
      if (stopContainer) stopContainer.classList.remove('hidden')
      break
    case 'round_start': updateThinkingStatusCurrent(`Round ${msg.round}`); break
    case 'model_start': addThinkingEntry(msg.label || msg.model); break
    case 'token':
      if (msg.phase === 'summary') appendToFinalAnswerCurrent(msg.token)
      else appendToThinkingEntry(msg.model, msg.token)
      break
    case 'model_done': finishThinkingEntry(msg.model); break
    case 'time_up': updateThinkingStatusCurrent('finalizing'); break
    case 'voting': updateThinkingStatusCurrent('voting'); break
    case 'consensus':
      updateThinkingStatusCurrent('complete')
      const stopCont = document.getElementById(`stop-thinking-container-${window.currentMessageId}`)
      if (stopCont) stopCont.classList.add('hidden')
      const finalEl = document.getElementById(`final-answer-${window.currentMessageId}`)
      if (finalEl) {
        finalEl.dataset.raw = msg.summary
        finalEl.innerHTML = marked.parse(msg.summary)
      }
      debating = false
      document.getElementById('send-btn').disabled = false
      document.getElementById('send-btn-center').disabled = false
      scrollToBottom()
      break
  }
}

function updateThinkingStatusCurrent(text) {
  const el = document.getElementById(`thinking-status-${window.currentMessageId}`)
  if (el) el.textContent = text
}

function addThinkingEntry(label) {
  if (!currentThinkingContent) return
  const entry = document.createElement('div')
  entry.className = 'thinking-entry pl-3 py-2'
  entry.innerHTML = `
    <div class="text-xs text-[#666] mb-1 font-medium">${label}</div>
    <div id="text-${label}" class="thinking-text"></div>
  `
  currentThinkingContent.appendChild(entry)
}

function appendToThinkingEntry(model, token) {
  const entries = currentThinkingContent?.querySelectorAll('[id^="text-"]')
  if (!entries) return
  const lastEntry = entries[entries.length - 1]
  if (!lastEntry) return
  const cursor = lastEntry.querySelector('.cursor')
  if (cursor) {
    cursor.insertAdjacentText('beforebegin', token)
  } else {
    lastEntry.textContent += token
    const c = document.createElement('span')
    c.className = 'cursor'
    lastEntry.appendChild(c)
  }
  if (currentThinkingContent) currentThinkingContent.scrollTop = currentThinkingContent.scrollHeight
}

function finishThinkingEntry(model) {
  const entries = currentThinkingContent?.querySelectorAll('[id^="text-"]')
  if (!entries) return
  entries[entries.length - 1]?.querySelector('.cursor')?.remove()
}

function appendToFinalAnswerCurrent(token) {
  const el = document.getElementById(`final-answer-${window.currentMessageId}`)
  if (!el) return
  if (!el.dataset.raw) el.dataset.raw = ''
  el.dataset.raw += token
  el.innerHTML = marked.parse(el.dataset.raw)
  scrollToBottom()
}

function appendToFinalAnswer(token) {
  const el = document.getElementById('final-answer')
  if (!el) return
  if (!el.dataset.raw) el.dataset.raw = ''
  el.dataset.raw += token
  // Parse markdown and render as HTML
  el.innerHTML = marked.parse(el.dataset.raw)
  scrollToBottom()
}

function copyAnswerById(id) {
  const el = document.getElementById(`final-answer-${id}`)
  if (!el) return
  const text = el.dataset.raw || el.textContent
  navigator.clipboard.writeText(text).then(() => {
    const icon = document.getElementById(`copy-icon-${id}`)
    const textEl = document.getElementById(`copy-text-${id}`)
    if (icon) icon.className = 'fa-solid fa-check'
    if (textEl) textEl.textContent = 'Copied!'
    setTimeout(() => {
      if (icon) icon.className = 'fa-regular fa-copy'
      if (textEl) textEl.textContent = 'Copy'
    }, 2000)
  })
}

function copyAnswer() {
  const el = document.getElementById('final-answer')
  if (!el) return
  const text = el.dataset.raw || el.textContent
  navigator.clipboard.writeText(text).then(() => {
    const icon = document.getElementById('copy-icon')
    const textEl = document.getElementById('copy-text')
    icon.className = 'fa-solid fa-check'
    textEl.textContent = 'Copied!'
    setTimeout(() => {
      icon.className = 'fa-regular fa-copy'
      textEl.textContent = 'Copy'
    }, 2000)
  })
}
function stripMarkdown(text) {
  return text
    .replace(/^#{1,6}\s+/gm, '')           // headings
    .replace(/\*\*(.+?)\*\*/g, '$1')        // bold
    .replace(/\*(.+?)\*/g, '$1')            // italic
    .replace(/~~(.+?)~~/g, '$1')            // strikethrough
    .replace(/`{3}[\s\S]*?`{3}/g, '')       // code blocks
    .replace(/`(.+?)`/g, '$1')              // inline code
    .replace(/^\s*[-*+]\s+/gm, '• ')        // unordered lists
    .replace(/^\s*\d+\.\s+/gm, '')          // ordered lists
    .replace(/\[(.+?)\]\(.+?\)/g, '$1')     // links
    .replace(/!\[.*?\]\(.+?\)/g, '')        // images
    .replace(/^[-*_]{3,}$/gm, '')           // horizontal rules
    .replace(/>\s+/g, '')                   // blockquotes
    .replace(/\n{3,}/g, '\n\n')             // excess newlines
    .trim()
}
function exportAllConversations() {
  const container = document.getElementById('chat-container')
  if (!container || container.children.length === 0) return

  if (typeof window.jspdf === 'undefined' && typeof jsPDF === 'undefined') {
    alert('PDF library not loaded. Please refresh.')
    return
  }

  const { jsPDF } = window.jspdf || window

  const doc = new jsPDF({ unit: 'pt', format: 'letter' })
  const pageW = doc.internal.pageSize.getWidth()
  const pageH = doc.internal.pageSize.getHeight()
  const margin = 50
  const maxWidth = pageW - margin * 2
  let y = margin

  function checkPageBreak(needed = 20) {
    if (y + needed > pageH - margin) {
      doc.addPage()
      y = margin
    }
  }

  // Header
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(22)
  doc.setTextColor(0, 0, 0)
  doc.text('LacMind Conversation', margin, y)
  y += 24
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(10)
  doc.setTextColor(120, 120, 120)
  doc.text(new Date().toLocaleString(), margin, y)
  y += 30
  doc.setDrawColor(220, 220, 220)
  doc.line(margin, y, pageW - margin, y)
  y += 20

  container.querySelectorAll(':scope > div').forEach(msg => {
    const isUser = msg.classList.contains('justify-end')
    const label = isUser ? 'QUESTION' : 'ANSWER'
   const text = isUser
  ? (msg.querySelector('.answer-text')?.textContent || '').trim()
  : stripMarkdown(msg.querySelector('[id^="final-answer-"]')?.dataset.raw || msg.querySelector('[id^="final-answer-"]')?.textContent || '')
    if (!text) return

    checkPageBreak(40)

    // Label
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(9)
    doc.setTextColor(isUser ? 22 : 100, isUser ? 174 : 100, isUser ? 254 : 100)
    doc.text(label, margin, y)
    y += 16

    // Body text
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(11)
    doc.setTextColor(30, 30, 30)
    const lines = doc.splitTextToSize(text, maxWidth)
    lines.forEach(line => {
      checkPageBreak(16)
      doc.text(line, margin, y)
      y += 16
    })

    y += 20
    checkPageBreak(1)
    doc.setDrawColor(235, 235, 235)
    doc.line(margin, y, pageW - margin, y)
    y += 20
  })

  // Footer
  const totalPages = doc.internal.getNumberOfPages()
  for (let i = 1; i <= totalPages; i++) {
    doc.setPage(i)
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(9)
    doc.setTextColor(160, 160, 160)
    doc.text('Generated by LacMind · lacai.io', margin, pageH - 20)
    doc.text(`${i} / ${totalPages}`, pageW - margin, pageH - 20, { align: 'right' })
  }

  doc.save(`lacmind-${Date.now()}.pdf`)
}

function stopThinking() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'stop' }))
    updateThinkingStatusCurrent('stopping...')
    const stopCont = document.getElementById(`stop-thinking-container-${window.currentMessageId}`)
    if (stopCont) stopCont.classList.add('hidden')
  }
}

function newChat() {
  currentChatId = null
  currentThinkingContent = null
  debating = false
  document.getElementById('chat-container').innerHTML = ''
  document.getElementById('chat-mode').classList.add('hidden')
  document.getElementById('centered-input').classList.remove('hidden')
  document.getElementById('prompt-input-center').value = ''
  document.getElementById('prompt-input').value = ''
  document.getElementById('export-btn').disabled = true
  document.getElementById('export-btn').classList.remove('text-[#666]')
  document.getElementById('export-btn').classList.add('text-[#333]')
  document.getElementById('send-btn-center').disabled = false
  document.getElementById('send-btn').disabled = false
  clearError()
  history.pushState({}, '', '/')
}

function scrollToBottom() {
  const area = document.getElementById('chat-area-wrapper')
  if (area) area.scrollTo({ top: area.scrollHeight, behavior: 'smooth' })
}

function showError(msg) {
  document.getElementById('error-text').textContent = msg
  document.getElementById('error-banner').classList.remove('hidden')
}

function clearError() {
  document.getElementById('error-banner').classList.add('hidden')
}

function escapeHtml(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
}

loadModels()
