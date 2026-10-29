const authScreen = document.querySelector('#auth');
const application = document.querySelector('#application');
const authForm = document.querySelector('#auth-form');
const navigation = document.querySelector('#navigation');
const dashboard = document.querySelector('#dashboard');
const modulePanel = document.querySelector('#module-panel');
const toast = document.querySelector('#toast');

const icons = {
  dashboard: '⌂', employees: '♙', departments: '▦', positions: '▤',
  dependents: '♡', payslips: '＄', attendance: '◷', vacations: '▣',
  trainings: '▱', users: '♧', settings: '⚙',
};
const pageTitles = {
  dashboard: 'Visão geral', departments: 'Departamentos',
  positions: 'Cargos', settings: 'Configurações',
};
let csrfToken = '';
let currentUser = null;
let currentModule = 'dashboard';
let moduleState = null;
let editingId = null;
let toastTimer;

function showToast(message, isError = false) {
  toast.textContent = message;
  toast.classList.toggle('error', isError);
  toast.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('visible'), 3500);
}

async function api(url, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body) headers['Content-Type'] = 'application/json';
  if (options.method && options.method !== 'GET') headers['X-CSRF-Token'] = csrfToken;
  const response = await fetch(url, { ...options, headers });
  const result = response.status === 204 ? {} : await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && currentUser) {
      currentUser = null;
      try {
        const sessionResponse = await fetch('/api/session');
        const state = await sessionResponse.json();
        csrfToken = state.csrf_token;
        showAuth(state.needs_setup);
      } catch (sessionError) {
        showAuth(false);
        showToast(`Não foi possível renovar a sessão: ${sessionError.message}`, true);
      }
    }
    throw new Error(result.error || `Não foi possível concluir a operação (${response.status}).`);
  }
  return result;
}

function showAuth(needsSetup) {
  application.hidden = true;
  authScreen.hidden = false;
  document.querySelector('#auth-title').textContent = needsSetup ? 'Criar administrador' : 'Acessar o sistema';
  document.querySelector('#auth-description').textContent = needsSetup
    ? 'Crie a primeira conta para administrar o Sistema de Gestão Corporativo.'
    : 'Informe suas credenciais para continuar.';
  document.querySelector('#confirmation-field').hidden = !needsSetup;
  document.querySelector('#auth-form [name="confirmation"]').required = needsSetup;
  document.querySelector('#auth-form [name="password"]').autocomplete = needsSetup ? 'new-password' : 'current-password';
  document.querySelector('#auth-submit').textContent = needsSetup ? 'Criar conta e entrar' : 'Entrar';
  authForm.dataset.setup = String(needsSetup);
}

async function initialize() {
  try {
    const state = await api('/api/session');
    csrfToken = state.csrf_token;
    currentUser = state.user;
    document.documentElement.dataset.theme = 'light';
    if (!currentUser) {
      showAuth(state.needs_setup);
      return;
    }
    await openApplication();
  } catch (error) {
    showToast(error.message, true);
  }
}

authForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(authForm));
  const isSetup = authForm.dataset.setup === 'true';
  try {
    const result = await api(isSetup ? '/api/auth/setup' : '/api/auth/login', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    currentUser = result.user;
    const state = await api('/api/session');
    csrfToken = state.csrf_token;
    authForm.reset();
    await openApplication();
  } catch (error) {
    showToast(error.message, true);
  }
});

async function openApplication() {
  authScreen.hidden = true;
  application.hidden = false;
  document.querySelector('#user-name').textContent = currentUser.username;
  document.querySelector('#user-role').textContent = currentUser.role;
  document.querySelector('#user-avatar').textContent = currentUser.username.slice(0, 1).toUpperCase();
  const data = await api('/api/dashboard');
  document.documentElement.dataset.theme = data.settings.theme;
  renderNavigation(data.modules);
  await openModule('dashboard');
}

function renderNavigation(modules) {
  navigation.replaceChildren();
  const options = [{ key: 'dashboard', title: 'Visão geral' }, ...modules];
  for (const item of options) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'nav-item';
    button.dataset.module = item.key;
    const icon = document.createElement('span');
    icon.className = 'nav-icon';
    icon.textContent = icons[item.key] || '•';
    const title = document.createElement('span');
    title.textContent = item.title;
    button.append(icon, title);
    button.addEventListener('click', () => openModule(item.key));
    navigation.append(button);
  }
}

async function openModule(key) {
  currentModule = key;
  editingId = null;
  document.querySelectorAll('.nav-item').forEach((item) => {
    item.classList.toggle('active', item.dataset.module === key);
  });
  dashboard.hidden = key !== 'dashboard';
  modulePanel.hidden = key === 'dashboard';
  document.querySelector('#page-title').textContent = pageTitles[key]
    || navigation.querySelector(`[data-module="${CSS.escape(key)}"] span:last-child`)?.textContent
    || key;
  if (key === 'dashboard') return renderDashboard();
  if (key === 'settings') return renderSettings();
  modulePanel.replaceChildren();
  try {
    moduleState = await api(`/api/modules/${key}`);
    renderModule(moduleState);
  } catch (error) {
    showToast(error.message, true);
  }
}

async function renderDashboard() {
  try {
    const data = await api('/api/dashboard');
    dashboard.replaceChildren();
    const cards = [
      ['Total colaboradores', data.kpis.employees],
      ['Média salarial', formatCurrency(data.kpis.average_salary)],
      ['Total de departamentos', data.kpis.departments],
      ['Férias pendentes', data.kpis.pending_vacations],
    ];
    const grid = document.createElement('div');
    grid.className = 'kpi-grid';
    cards.forEach(([label, value]) => {
      const card = document.createElement('article');
      card.className = 'kpi-card';
      const caption = document.createElement('span');
      caption.textContent = label;
      const metric = document.createElement('strong');
      metric.textContent = value;
      card.append(caption, metric);
      grid.append(card);
    });
    const welcome = document.createElement('section');
    welcome.className = 'panel';
    const heading = document.createElement('div');
    heading.className = 'panel-heading';
    const title = document.createElement('h2');
    title.textContent = 'Gestão de pessoas em um só lugar';
    heading.append(title);
    const content = document.createElement('div');
    content.className = 'settings-grid';
    const description = document.createElement('p');
    description.className = 'muted';
    description.textContent = 'Acesse os módulos pelo menu para consultar e administrar colaboradores, folha, ponto, férias e treinamentos.';
    content.append(description);
    const actions = document.createElement('div');
    actions.className = 'dashboard-actions';
    const logout = makeButton('Sair do sistema', 'button danger');
    logout.addEventListener('click', () => endSession('Você saiu do sistema.'));
    actions.append(logout);
    content.append(actions);
    welcome.append(heading, content);
    dashboard.append(grid, welcome);
  } catch (error) {
    showToast(error.message, true);
  }
}

function renderModule(data) {
  modulePanel.replaceChildren();
  modulePanel.classList.remove('printing');
  const layout = document.createElement('div');
  layout.className = `module-layout${data.fields.length ? '' : ' readonly'}`;
  if (data.fields.length) layout.append(createForm(data));
  const panel = document.createElement('section');
  panel.className = 'panel data-panel';
  const heading = document.createElement('div');
  heading.className = 'panel-heading';
  const title = document.createElement('h2');
  title.textContent = data.title;
  heading.append(title);
  const tools = document.createElement('div');
  tools.className = 'report-tools';
  const printNames = {
    dependents: 'dependentes',
    payslips: 'contracheques',
    attendance: 'registros de ponto',
    vacations: 'solicitações de férias',
    trainings: 'treinamentos',
  };
  const printName = printNames[data.key] || data.title.toLowerCase();
  if (data.key === 'dependents') {
    const employeeSelect = document.createElement('select');
    employeeSelect.className = 'print-employee-select';
    employeeSelect.setAttribute('aria-label', 'Funcionário para imprimir dependentes');
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Selecionar funcionário';
    employeeSelect.append(placeholder);
    data.employees.forEach((employee) => {
      const option = document.createElement('option');
      option.value = employee.id;
      option.textContent = employee.nome;
      employeeSelect.append(option);
    });
    tools.append(employeeSelect);
  }
  const print = makeButton(
    `Imprimir ${printName}`,
    'button quiet',
  );
  if (data.key === 'dependents') print.disabled = true;
  const dependentSelect = tools.querySelector('.print-employee-select');
  dependentSelect?.addEventListener('change', () => {
    print.disabled = !dependentSelect.value;
  });
  print.addEventListener('click', () => printModuleReport(data, panel, false));
  tools.append(print);
  if (data.key === 'dependents') {
    const printCompleteReport = makeButton('Imprimir relatório completo', 'button quiet');
    printCompleteReport.addEventListener('click', () => printModuleReport(data, panel, false, true));
    tools.append(printCompleteReport);
  }
  if (['payslips', 'attendance', 'vacations', 'trainings'].includes(data.key)) {
    const selectedPrintNames = {
      payslips: 'contracheques selecionados',
      attendance: 'registros de ponto selecionados',
      vacations: 'solicitações de férias selecionadas',
      trainings: 'treinamentos selecionados',
    };
    const printSelected = makeButton(`Imprimir ${selectedPrintNames[data.key]}`, 'button quiet');
    printSelected.addEventListener('click', () => printModuleReport(data, panel, true));
    tools.append(printSelected);
  }
  heading.append(tools);
  panel.append(heading, createTable(data));
  layout.append(panel);
  modulePanel.append(layout);
  if (data.key === 'trainings') panel.append(createTrainingEnrollment(data));
  const printArea = document.createElement('section');
  printArea.className = `print-area print-area-${data.key}`;
  printArea.setAttribute('aria-label', 'Relatório para impressão');
  modulePanel.append(printArea);
}

function createForm(data) {
  const panel = document.createElement('section');
  panel.className = 'panel form-panel';
  const heading = document.createElement('h2');
  heading.textContent = data.key === 'employees' ? 'Novo colaborador'
    : data.key === 'trainings' ? 'Cadastro de treinamento'
      : `Novo registro: ${data.title.toLowerCase()}`;
  const description = document.createElement('p');
  description.className = 'muted';
  description.textContent = 'Preencha os campos para incluir as informações.';
  const form = document.createElement('form');
  form.className = 'form-fields';
  form.id = 'record-form';
  for (const field of data.fields) form.append(createField(field, data));
  const actions = document.createElement('div');
  actions.className = 'form-actions';
  const save = makeButton('Salvar registro', 'button primary');
  save.type = 'submit';
  save.id = 'save-record';
  actions.append(save);
  const cancel = makeButton('Cancelar edição', 'button');
  cancel.type = 'button';
  cancel.id = 'cancel-edit';
  cancel.hidden = true;
  cancel.addEventListener('click', () => resetRecordForm());
  actions.append(cancel);
  form.append(actions);
  form.addEventListener('submit', saveRecord);
  panel.append(heading, description, form);
  return panel;
}

function createField(field, data) {
  const label = document.createElement('label');
  label.textContent = field.label;
  let input;
  if (['employee', 'relationship', 'modality', 'role'].includes(field.type)) {
    input = document.createElement('select');
    const values = field.type === 'employee'
      ? data.employees.map((employee) => [employee.id, `${employee.id} - ${employee.nome}`])
      : field.type === 'relationship' ? data.relationships.map((value) => [value, value])
        : field.type === 'modality' ? data.modalities.map((value) => [value, value])
          : [['Usuário', 'Usuário'], ['Administrador', 'Administrador']];
    for (const [value, text] of values) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = text;
      input.append(option);
    }
  } else {
    input = document.createElement('input');
    input.type = field.type === 'positive_integer' ? 'number'
      : field.type === 'month' ? 'text' : field.type;
    if (field.type === 'number') {
      input.step = '0.01';
      input.min = '0';
    } else if (field.type === 'positive_integer') {
      input.step = '1';
      input.min = '1';
    } else if (field.type === 'month') {
      input.placeholder = 'MM/AAAA';
      input.maxLength = 7;
    }
  }
  input.name = field.key;
  input.required = true;
  label.append(input);
  return label;
}

async function saveRecord(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form));
  try {
    if (currentModule === 'payslips') {
      payload.salario_bruto = Number(payload.salario_bruto);
      payload.descontos = Number(payload.descontos);
    }
    if (['employees', 'trainings'].includes(currentModule)) {
      const numericField = currentModule === 'employees' ? 'salario' : 'carga_horaria';
      payload[numericField] = Number(payload[numericField]);
    }
    const editing = editingId !== null;
    await api(`/api/modules/${currentModule}${editing ? `/${editingId}` : ''}`, {
      method: editing ? 'PATCH' : 'POST',
      body: JSON.stringify(payload),
    });
    showToast(editing ? 'Registro atualizado.' : 'Registro cadastrado.');
    editingId = null;
    await openModule(currentModule);
  } catch (error) {
    showToast(error.message, true);
  }
}

function createTable(data) {
  const wrap = document.createElement('div');
  wrap.className = 'table-wrap';
  const table = document.createElement('table');
  const head = document.createElement('thead');
  const headRow = document.createElement('tr');
  const supportsSelection = ['payslips', 'attendance', 'vacations', 'trainings'].includes(data.key);
  if (supportsSelection) {
    const selectHeading = document.createElement('th');
    selectHeading.textContent = 'Selecionar';
    headRow.append(selectHeading);
  }
  data.columns.forEach((column) => {
    const th = document.createElement('th');
    th.textContent = column.label;
    headRow.append(th);
  });
  if (data.fields.length) {
    const actions = document.createElement('th');
    actions.textContent = 'Ações';
    headRow.append(actions);
  }
  head.append(headRow);
  const body = document.createElement('tbody');
  if (!data.rows.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.className = 'empty-cell';
    td.colSpan = data.columns.length + Number(data.fields.length > 0) + Number(supportsSelection);
    td.textContent = 'Nenhum registro encontrado.';
    tr.append(td);
    body.append(tr);
  } else {
    data.rows.forEach((row) => {
      const tr = document.createElement('tr');
      if (row.id !== undefined) tr.dataset.recordId = row.id;
      if (supportsSelection) {
        const selectCell = document.createElement('td');
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.setAttribute('aria-label', `Selecionar ${row.nome || row.titulo || row.username || row.id} para imprimir`);
        selectCell.append(checkbox);
        tr.append(selectCell);
      }
      data.columns.forEach((column) => {
        const td = document.createElement('td');
        const value = row[column.key];
        td.textContent = formatCell(column.key, value);
        tr.append(td);
      });
      if (data.fields.length) tr.append(createRowActions(row, data));
      body.append(tr);
    });
  }
  table.append(head, body);
  wrap.append(table);
  return wrap;
}

function createRowActions(row, data) {
  const td = document.createElement('td');
  const actions = document.createElement('div');
  actions.className = 'row-actions';
  const edit = makeButton('Editar', 'button');
  edit.addEventListener('click', () => editRecord(row, data));
  if (data.key === 'vacations' && row.status === 'Pendente') {
    const complete = makeButton('Cumprir', 'button');
    complete.addEventListener('click', async () => {
      try {
        await api(`/api/vacations/${row.id}/complete`, { method: 'POST', body: '{}' });
        showToast('Férias marcadas como cumpridas.');
        await openModule(data.key);
      } catch (error) {
        showToast(error.message, true);
      }
    });
    actions.append(complete);
  }
  const remove = makeButton('Excluir', 'button danger');
  remove.addEventListener('click', () => deleteRecord(row, data));
  actions.append(edit, remove);
  td.append(actions);
  return td;
}

function editRecord(row, data) {
  editingId = row.id;
  const form = document.querySelector('#record-form');
  data.fields.forEach((field) => {
    const input = form.elements[field.key];
    if (input) input.value = row[field.key] ?? '';
  });
  if (data.key === 'users') {
    form.elements.password.value = '';
    form.elements.password.required = false;
  }
  document.querySelector('#save-record').textContent = 'Salvar alterações';
  document.querySelector('#cancel-edit').hidden = false;
  form.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

async function deleteRecord(row, data) {
  const itemName = row.nome || row.titulo || row.username || row.colaborador || `#${row.id}`;
  if (!window.confirm(`Deseja excluir "${itemName}"?`)) return;
  try {
    await api(`/api/modules/${data.key}/${row.id}`, { method: 'DELETE' });
    showToast('Registro excluído.');
    await openModule(data.key);
  } catch (error) {
    showToast(error.message, true);
  }
}

function resetRecordForm() {
  editingId = null;
  document.querySelector('#record-form')?.reset();
  const password = document.querySelector('#record-form [name="password"]');
  if (password) password.required = true;
  const save = document.querySelector('#save-record');
  const cancel = document.querySelector('#cancel-edit');
  if (save) save.textContent = 'Salvar registro';
  if (cancel) cancel.hidden = true;
}

function createTrainingEnrollment(data) {
  const panel = document.createElement('section');
  panel.className = 'panel section-spacer';
  const heading = document.createElement('div');
  heading.className = 'panel-heading';
  const title = document.createElement('h2');
  title.textContent = 'Inscrições em treinamentos';
  heading.append(title);
  panel.append(heading);
  const form = document.createElement('form');
  form.className = 'inline-form';
  const trainingLabel = document.createElement('label');
  trainingLabel.textContent = 'Treinamento';
  const trainingSelect = document.createElement('select');
  trainingSelect.name = 'training_id';
  data.rows.forEach((course) => {
    const option = document.createElement('option');
    option.value = course.id;
    option.textContent = course.titulo;
    trainingSelect.append(option);
  });
  trainingLabel.append(trainingSelect);
  const employeeLabel = document.createElement('label');
  employeeLabel.textContent = 'Colaborador';
  const employeeSelect = document.createElement('select');
  employeeSelect.name = 'funcionario_id';
  data.employees.forEach((employee) => {
    const option = document.createElement('option');
    option.value = employee.id;
    option.textContent = `${employee.id} - ${employee.nome}`;
    employeeSelect.append(option);
  });
  employeeLabel.append(employeeSelect);
  const submit = makeButton('Inscrever', 'button primary');
  submit.type = 'submit';
  form.append(trainingLabel, employeeLabel, submit);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!trainingSelect.value || !employeeSelect.value) {
      showToast('Cadastre um treinamento e um colaborador antes de inscrever.', true);
      return;
    }
    try {
      await api(`/api/trainings/${trainingSelect.value}/enrollments`, {
        method: 'POST',
        body: JSON.stringify({ funcionario_id: Number(employeeSelect.value) }),
      });
      showToast('Colaborador inscrito no treinamento.');
      await openModule('trainings');
    } catch (error) {
      showToast(error.message, true);
    }
  });
  panel.append(form);
  const rosterTitle = document.createElement('div');
  rosterTitle.className = 'panel-heading';
  const rosterHeading = document.createElement('h2');
  rosterHeading.textContent = 'Colaboradores inscritos';
  rosterTitle.append(rosterHeading);
  panel.append(rosterTitle);
  const roster = document.createElement('div');
  roster.className = 'table-wrap';
  const table = document.createElement('table');
  const head = document.createElement('thead');
  const headRow = document.createElement('tr');
  ['Treinamento', 'Colaborador', 'Cargo', 'Setor', 'Ações'].forEach((text) => {
    const th = document.createElement('th');
    th.textContent = text;
    headRow.append(th);
  });
  head.append(headRow);
  const body = document.createElement('tbody');
  data.rows.forEach((course) => course.enrolled_employees.forEach((employee) => {
    const tr = document.createElement('tr');
    [course.titulo, employee.colaborador, employee.cargo, employee.setor].forEach((text) => {
      const td = document.createElement('td');
      td.textContent = text;
      tr.append(td);
    });
    const actionCell = document.createElement('td');
    const remove = makeButton('Remover inscrição', 'button danger');
    remove.addEventListener('click', async () => {
      if (!window.confirm(`Remover ${employee.colaborador} deste treinamento?`)) return;
      try {
        await api(`/api/trainings/${course.id}/enrollments/${employee.id}`, { method: 'DELETE' });
        showToast('Inscrição removida.');
        await openModule('trainings');
      } catch (error) {
        showToast(error.message, true);
      }
    });
    actionCell.append(remove);
    tr.append(actionCell);
    body.append(tr);
  }));
  if (!body.children.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 5;
    td.className = 'empty-cell';
    td.textContent = 'Nenhuma inscrição cadastrada.';
    tr.append(td);
    body.append(tr);
  }
  table.append(head, body);
  roster.append(table);
  panel.append(roster);
  return panel;
}

async function renderSettings() {
  try {
    const data = await api('/api/dashboard');
    const settings = data.settings;
    modulePanel.replaceChildren();
    const panel = document.createElement('section');
    panel.className = 'panel';
    const heading = document.createElement('div');
    heading.className = 'panel-heading';
    const title = document.createElement('h2');
    title.textContent = 'Configurações do aplicativo';
    heading.append(title);
    panel.append(heading);
    const grid = document.createElement('div');
    grid.className = 'settings-grid';
    const themeRow = document.createElement('div');
    themeRow.className = 'settings-row';
    const themeText = document.createElement('div');
    themeText.innerHTML = '<h2>Tema</h2><p>Escolha a aparência do sistema.</p>';
    const themeSelect = document.createElement('select');
    [['light', 'Claro'], ['dark', 'Escuro']].forEach(([value, label]) => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = label;
      themeSelect.append(option);
    });
    themeSelect.value = settings.theme;
    themeSelect.addEventListener('change', async () => {
      try {
        await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ theme: themeSelect.value }) });
        document.documentElement.dataset.theme = themeSelect.value;
        showToast('Tema atualizado.');
      } catch (error) {
        showToast(error.message, true);
      }
    });
    themeRow.append(themeText, themeSelect);
    grid.append(themeRow);
    if (currentUser.role === 'Administrador') {
      const dbRow = document.createElement('div');
      dbRow.className = 'settings-row';
      const dbText = document.createElement('div');
      dbText.innerHTML = '<h2>Pasta do banco de dados</h2><p>A alteração será usada na próxima inicialização. Os dados não serão movidos ou copiados.</p>';
      const controls = document.createElement('div');
      const directory = document.createElement('input');
      directory.value = settings.database_directory || settings.default_database_directory;
      directory.setAttribute('aria-label', 'Pasta do banco de dados');
      const defaultButton = makeButton('Usar padrão do sistema', 'button');
      defaultButton.type = 'button';
      defaultButton.style.marginTop = '8px';
      defaultButton.addEventListener('click', () => {
        directory.value = settings.default_database_directory;
        saveDatabaseDirectory(null);
      });
      const saveButton = makeButton('Salvar pasta', 'button primary');
      saveButton.type = 'button';
      saveButton.style.marginTop = '8px';
      saveButton.style.marginRight = '8px';
      saveButton.addEventListener('click', () => saveDatabaseDirectory(directory.value));
      controls.append(directory, saveButton, defaultButton);
      dbRow.append(dbText, controls);
      grid.append(dbRow);
      const location = document.createElement('p');
      location.className = 'muted';
      location.textContent = `Arquivo do banco atual: ${settings.database_path}`;
      grid.append(location);
    } else {
      const info = document.createElement('p');
      info.className = 'muted';
      info.textContent = 'Somente administradores podem alterar a pasta do banco de dados.';
      grid.append(info);
    }
    panel.append(grid);
    modulePanel.append(panel);

    async function saveDatabaseDirectory(path) {
      try {
        await api('/api/settings', {
          method: 'PATCH',
          body: JSON.stringify({ database_directory: path }),
        });
        showToast('Pasta do banco salva; será utilizada na próxima inicialização.');
        await renderSettings();
      } catch (error) {
        showToast(error.message, true);
      }
    }
  } catch (error) {
    showToast(error.message, true);
  }
}

document.querySelector('#theme-toggle').addEventListener('click', async () => {
  const theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  try {
    await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ theme }) });
    document.documentElement.dataset.theme = theme;
    showToast(`Tema ${theme === 'dark' ? 'escuro' : 'claro'} ativado.`);
  } catch (error) {
    showToast(error.message, true);
  }
});

document.querySelector('#logout').addEventListener('click', () => endSession('Você saiu do sistema.'));

async function endSession(message) {
  try {
    await api('/api/auth/logout', { method: 'POST', body: '{}' });
    currentUser = null;
    const state = await api('/api/session');
    csrfToken = state.csrf_token;
    authForm.reset();
    showAuth(false);
    showToast(message);
  } catch (error) {
    showToast(error.message, true);
  }
}

function makeButton(text, className) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = className;
  button.textContent = text;
  return button;
}

function formatCurrency(value) {
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(Number(value || 0));
}

function formatCell(key, value) {
  if (value === null || value === undefined) return '';
  if (['salario', 'salario_atual', 'salario_bruto', 'descontos', 'salario_liquido', 'media_salarial'].includes(key)) {
    return formatCurrency(value);
  }
  return String(value);
}

function printModuleReport(data, panel, selectedOnly, completeReport = false) {
  let rows = data.rows;
  if (data.key === 'dependents' && !completeReport) {
    const employeeId = Number(panel.querySelector('.print-employee-select')?.value);
    if (!employeeId) {
      showToast('Selecione o funcionário para imprimir todos os seus dependentes.', true);
      return;
    }
    rows = data.rows.filter((row) => row.funcionario_id === employeeId);
  } else if (selectedOnly) {
    const selectedIds = new Set(
      [...panel.querySelectorAll('tbody input[type="checkbox"]:checked')]
        .map((checkbox) => Number(checkbox.closest('tr').dataset.recordId)),
    );
    if (selectedIds.size === 0) {
      showToast('Selecione ao menos um registro para imprimir.', true);
      return;
    }
    rows = data.rows.filter((row) => selectedIds.has(row.id));
  }

  const area = modulePanel.querySelector('.print-area');
  area.replaceChildren();
  const heading = document.createElement('header');
  heading.className = `print-header print-header-${data.key}`;
  const appName = document.createElement('p');
  appName.className = 'print-app-name';
  appName.textContent = 'Sistema de Gestão Corporativo';
  const reportTitle = document.createElement('h1');
  if (data.key === 'dependents' && completeReport) {
    reportTitle.textContent = 'Relatório completo de dependentes';
  } else if (data.key === 'dependents') {
    reportTitle.textContent = `Dependentes de ${panel.querySelector('.print-employee-select').selectedOptions[0].textContent}`;
  } else if (selectedOnly) {
    const selectedTitles = {
      payslips: 'Contracheques selecionados',
      attendance: 'Registros de ponto selecionados',
      vacations: 'Solicitações de férias selecionadas',
      trainings: 'Treinamentos selecionados',
    };
    reportTitle.textContent = selectedTitles[data.key] || `Registros selecionados de ${data.title}`;
  } else {
    reportTitle.textContent = `Relatório de ${data.title}`;
  }
  const issuedAt = document.createElement('p');
  issuedAt.className = 'print-generated-at';
  issuedAt.textContent = `Emitido em ${new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'long',
    timeStyle: 'short',
  }).format(new Date())}`;
  heading.append(appName, reportTitle, issuedAt);
  area.append(heading);

  if (data.key === 'dependents' && completeReport) {
    area.append(createPrintTable(data, rows));
  } else if (data.key === 'dependents') {
    appendDependentReport(area, rows);
  } else if (['payslips', 'attendance', 'vacations'].includes(data.key)) {
    rows.forEach((row) => area.append(createDetailedRecord(data.key, row)));
  } else if (data.key === 'trainings') {
    rows.forEach((row) => area.append(createTrainingReport(row)));
  } else {
    area.append(createPrintTable(data, rows));
  }

  modulePanel.classList.add('printing');
  window.addEventListener('afterprint', () => {
    modulePanel.classList.remove('printing');
    area.replaceChildren();
  }, { once: true });
  window.print();
}

function appendDependentReport(area, rows) {
  const roster = document.createElement('section');
  roster.className = 'print-record';
  const heading = document.createElement('h2');
  heading.textContent = `Total de dependentes: ${rows.length}`;
  roster.append(heading);
  if (!rows.length) {
    const empty = document.createElement('p');
    empty.className = 'print-empty';
    empty.textContent = 'Este funcionário não possui dependentes cadastrados.';
    roster.append(empty);
  } else {
    rows.forEach((row, index) => {
      roster.append(createPrintDetailGrid([
        [`Dependente ${index + 1}`, row.nome],
        ['Parentesco', row.parentesco],
      ]));
    });
  }
  area.append(roster);
}

function createDetailedRecord(module, row) {
  const details = {
    payslips: [
      ['Colaborador', row.colaborador],
      ['Cargo', row.cargo],
      ['Setor', row.setor],
      ['Referência', row.mes_ano],
      ['Salário bruto', formatCurrency(row.salario_bruto)],
      ['Descontos', formatCurrency(row.descontos)],
      ['Salário líquido', formatCurrency(row.salario_liquido)],
    ],
    attendance: [
      ['Colaborador', row.colaborador],
      ['Cargo', row.cargo],
      ['Setor', row.setor],
      ['Data do registro', formatDate(row.data)],
      ['Horário de entrada', row.entrada],
      ['Horário de saída', row.saida],
      ['Jornada registrada', calculateShift(row.entrada, row.saida)],
    ],
    vacations: [
      ['Colaborador', row.colaborador],
      ['Cargo', row.cargo],
      ['Setor', row.setor],
      ['Início das férias', formatDate(row.inicio)],
      ['Fim das férias', formatDate(row.fim)],
      ['Duração', vacationDuration(row.inicio, row.fim)],
      ['Status da solicitação', row.status],
    ],
  }[module];
  const card = document.createElement('article');
  card.className = 'print-record';
  const title = document.createElement('h2');
  title.textContent = module === 'payslips'
    ? `Contracheque — ${row.colaborador} — ${row.mes_ano}`
    : module === 'attendance'
      ? `Registro de ponto — ${row.colaborador} — ${formatDate(row.data)}`
      : `Solicitação de férias — ${row.colaborador}`;
  card.append(title, createPrintDetailGrid(details));
  return card;
}

function createPrintDetailGrid(details) {
  const grid = document.createElement('dl');
  grid.className = 'print-detail-grid';
  details.forEach(([label, value]) => {
    const item = document.createElement('div');
    const term = document.createElement('dt');
    term.textContent = label;
    const description = document.createElement('dd');
    description.textContent = value == null || value === '' ? '—' : String(value);
    item.append(term, description);
    grid.append(item);
  });
  return grid;
}

function createTrainingReport(course) {
  const card = document.createElement('article');
  card.className = 'print-record';
  const title = document.createElement('h2');
  title.textContent = course.titulo;
  card.append(title, createPrintDetailGrid([
    ['Categoria', course.categoria],
    ['Carga horária', `${course.carga_horaria} horas`],
    ['Modalidade', course.modalidade],
    ['Total de inscritos', course.enrolled_employees.length],
  ]));
  const rosterTitle = document.createElement('h3');
  rosterTitle.className = 'print-roster-title';
  rosterTitle.textContent = 'Colaboradores inscritos';
  card.append(rosterTitle);
  if (!course.enrolled_employees.length) {
    const empty = document.createElement('p');
    empty.className = 'print-empty';
    empty.textContent = 'Nenhum colaborador inscrito neste treinamento.';
    card.append(empty);
  } else {
    const roster = document.createElement('div');
    roster.className = 'print-roster';
    course.enrolled_employees.forEach((employee) => {
      roster.append(createPrintDetailGrid([
        ['Colaborador', employee.colaborador],
        ['Cargo', employee.cargo],
        ['Setor', employee.setor],
      ]));
    });
    card.append(roster);
  }
  return card;
}

function createPrintTable(data, rows) {
  const table = document.createElement('table');
  table.className = 'print-table';
  const head = document.createElement('thead');
  const headRow = document.createElement('tr');
  data.columns.forEach((column) => {
    const th = document.createElement('th');
    th.textContent = column.label;
    headRow.append(th);
  });
  head.append(headRow);
  const body = document.createElement('tbody');
  rows.forEach((row) => {
    const tr = document.createElement('tr');
    data.columns.forEach((column) => {
      const td = document.createElement('td');
      td.textContent = formatCell(column.key, row[column.key]);
      tr.append(td);
    });
    body.append(tr);
  });
  if (!rows.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = data.columns.length;
    td.textContent = 'Nenhum registro cadastrado.';
    tr.append(td);
    body.append(tr);
  }
  table.append(head, body);
  return table;
}

function formatDate(value) {
  if (!value) return '—';
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? value : new Intl.DateTimeFormat('pt-BR').format(parsed);
}

function calculateShift(start, end) {
  if (!start || !end || !start.includes(':') || !end.includes(':')) return '—';
  const toMinutes = (time) => {
    const [hours, minutes] = time.split(':').map(Number);
    return hours * 60 + minutes;
  };
  let duration = toMinutes(end) - toMinutes(start);
  if (duration < 0) duration += 24 * 60;
  return `${Math.floor(duration / 60)}h ${String(duration % 60).padStart(2, '0')}min`;
}

function vacationDuration(start, end) {
  const startDate = new Date(`${start}T00:00:00`);
  const endDate = new Date(`${end}T00:00:00`);
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return '—';
  const days = Math.floor((endDate - startDate) / 86_400_000) + 1;
  return `${days} ${days === 1 ? 'dia' : 'dias'}`;
}

initialize();
