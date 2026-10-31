from pathlib import Path
from contextlib import contextmanager
from datetime import date, datetime
import html
from html.parser import HTMLParser
import ctypes
import hashlib
import hmac
import json
import os
import sqlite3
import tkinter as tk
import textwrap
from tkinter import filedialog, ttk, messagebox

PASSWORD_HASH_ITERATIONS = 310_000
APPDATA = Path(os.environ.get('APPDATA') or os.path.expanduser('~'))
DB_DIR = APPDATA / 'NexusRHPro'
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / 'nexus_rh_pro.db'
SETTINGS_PATH = DB_DIR / 'settings.json'
DEFAULT_SETTINGS = {'database_directory': None, 'theme': 'light'}
APP_SETTINGS = DEFAULT_SETTINGS.copy()

LIGHT_TO_DARK_BACKGROUND = {
    '#ffffff': '#1e293b',
    'white': '#1e293b',
    '#f3f4f6': '#0f172a',
    '#e2e8f0': '#334155',
    '#ecfdf5': '#064e3b',
}
LIGHT_TO_DARK_FOREGROUND = {
    '#0f172a': '#f1f5f9',
    '#111827': '#f1f5f9',
    '#475569': '#cbd5e1',
    '#64748b': '#94a3b8',
    '#334155': '#cbd5e1',
    '#065f46': '#a7f3d0',
}
def load_app_settings():
    if not SETTINGS_PATH.exists():
        return DEFAULT_SETTINGS.copy()
    with SETTINGS_PATH.open(encoding='utf-8') as settings_file:
        settings = json.load(settings_file)
    if not isinstance(settings, dict):
        raise ValueError('O arquivo de configurações possui um formato inválido.')

    database_directory = settings.get('database_directory')
    if database_directory is not None and not isinstance(database_directory, str):
        raise ValueError('A pasta configurada para o banco de dados é inválida.')
    theme = settings.get('theme', 'light')
    if theme not in ('light', 'dark'):
        raise ValueError('O tema configurado é inválido.')
    return {'database_directory': database_directory, 'theme': theme}


def save_app_settings(settings):
    temporary_path = SETTINGS_PATH.with_suffix('.tmp')
    with temporary_path.open('w', encoding='utf-8') as settings_file:
        json.dump(settings, settings_file, ensure_ascii=False, indent=2)
    temporary_path.replace(SETTINGS_PATH)


def database_path_for_settings(settings):
    directory = settings['database_directory']
    return Path(directory) / 'nexus_rh_pro.db' if directory else DB_DIR / 'nexus_rh_pro.db'


def apply_widget_theme(root, theme):
    originals = getattr(root, '_theme_originals', None)
    if originals is None:
        originals = {}
        root._theme_originals = originals

    background_map = LIGHT_TO_DARK_BACKGROUND if theme == 'dark' else {}
    foreground_map = LIGHT_TO_DARK_FOREGROUND if theme == 'dark' else {}
    color_options = {
        'background': background_map,
        'activebackground': background_map,
        'highlightbackground': background_map,
        'selectbackground': background_map,
        'foreground': foreground_map,
        'activeforeground': foreground_map,
        'disabledforeground': foreground_map,
        'selectforeground': foreground_map,
    }
    neutral_surfaces = {
        'SystemButtonFace',
        'SystemWindow',
        'SystemWindowFrame',
        'SystemMenu',
    }
    accent_colors = {
        '#1d4ed8',
        '#2563eb',
        '#0369a1',
        '#0f766e',
        '#4f46e5',
        '#f59e0b',
        '#ef4444',
        '#14b8a6',
        '#10b981',
        '#16a34a',
    }

    def apply_to_widget(widget):
        if widget not in originals:
            originals[widget] = {
                option: widget.cget(option)
                for option in color_options
                if option in widget.keys()
            }
        for option, original_value in originals[widget].items():
            mapped_value = (
                color_options[option].get(original_value, original_value)
                if theme == 'dark'
                else original_value
            )
            widget.configure(**{option: mapped_value})
        widget_class = widget.winfo_class()
        if widget_class in ('Entry', 'Text', 'Listbox', 'Spinbox'):
            surface = '#1e293b' if theme == 'dark' else '#ffffff'
            foreground = '#f1f5f9' if theme == 'dark' else '#0f172a'
            widget.configure(
                background=surface,
                foreground=foreground,
                insertbackground=foreground,
                selectbackground='#2563eb',
                selectforeground='white',
            )
        elif widget_class == 'Button':
            original_background = originals[widget].get('background')
            if original_background in neutral_surfaces or (
                original_background not in accent_colors
                and original_background not in LIGHT_TO_DARK_BACKGROUND
            ):
                widget.configure(
                    background='#1e293b' if theme == 'dark' else '#ffffff',
                    foreground='#f1f5f9' if theme == 'dark' else '#0f172a',
                    activebackground='#334155' if theme == 'dark' else '#e2e8f0',
                )
        for child in widget.winfo_children():
            apply_to_widget(child)

    apply_to_widget(root)


class ReportTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.ignored_tags = 0
        self.active_tag = None
        self.active_text = []
        self.table_rows = None
        self.current_row = None
        self.current_cell = None
        self.current_cell_tag = None
        self.table_has_header = False
        self.in_table_header = False
        self.table_is_details = False

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.ignored_tags += 1
            return
        if self.ignored_tags:
            return
        if tag == 'table':
            self.flush_text()
            self.table_rows = []
            self.table_has_header = False
            self.in_table_header = False
            self.table_is_details = any(
                name == 'class' and 'details' in value.split()
                for name, value in attrs
            )
        elif self.table_rows is not None and tag == 'thead':
            self.table_has_header = True
            self.in_table_header = True
        elif self.table_rows is not None:
            if tag == 'tr':
                self.current_row = []
            elif tag in ('th', 'td'):
                self.current_cell = []
                self.current_cell_tag = tag
        elif tag in ('h1', 'h2', 'p'):
            self.flush_text()
            self.active_tag = tag
            self.active_text = []
        elif tag == 'br' and self.active_tag:
            self.active_text.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.ignored_tags:
            self.ignored_tags -= 1
            return
        if self.ignored_tags:
            return
        if tag in ('td', 'th') and self.current_cell is not None:
            value = ''.join(self.current_cell).strip()
            self.current_row.append((self.current_cell_tag, value))
            self.current_cell = None
            self.current_cell_tag = None
        elif tag == 'tr' and self.current_row is not None:
            self.table_rows.append(self.current_row)
            self.current_row = None
        elif tag == 'thead':
            self.in_table_header = False
        elif tag == 'table' and self.table_rows is not None:
            self.blocks.append(('table', self.table_rows, self.table_has_header, self.table_is_details))
            self.table_rows = None
            self.table_has_header = False
            self.table_is_details = False
        elif tag == self.active_tag:
            self.flush_text()

    def handle_data(self, data):
        if self.ignored_tags:
            return
        if self.current_cell is not None:
            self.current_cell.append(data)
        elif self.active_tag:
            self.active_text.append(data)

    def flush_text(self):
        if self.active_tag:
            text = ''.join(self.active_text).strip()
            if text:
                self.blocks.append((self.active_tag, text))
            self.active_tag = None
            self.active_text = []

    def get_lines(self):
        self.flush_text()
        lines = []
        for block in self.blocks:
            block_type, value = block[:2]
            if block_type == 'table':
                formatted_table = self.format_table(value, block[2], block[3])
                if formatted_table:
                    lines.extend(('', *formatted_table, ''))
            elif block_type == 'h1':
                if lines:
                    lines.append('')
                lines.extend((value, '=' * min(90, max(12, len(value)))))
            elif block_type == 'h2':
                if lines and lines[-1]:
                    lines.append('')
                lines.extend((value, '-' * min(90, max(8, len(value)))))
            else:
                lines.extend(textwrap.wrap(value, width=90) or [''])
        while lines and not lines[-1]:
            lines.pop()
        return lines

    @staticmethod
    def format_table(rows, has_header=False, is_details=False, max_width=100):
        if not rows:
            return []
        normalized_rows = [row for row in rows if row]
        if is_details:
            labels = [row[0][1] for row in normalized_rows if len(row) > 1]
            label_width = min(32, max((len(label) for label in labels), default=0))
            output = []
            for row in normalized_rows:
                if len(row) < 2:
                    output.append(row[0][1])
                    continue
                label, value = row[0][1], row[1][1]
                wrapped_value = textwrap.wrap(value, width=max(20, max_width - label_width - 3)) or ['']
                output.append(f'{label.ljust(label_width)} : {wrapped_value[0]}')
                output.extend(f'{" " * (label_width + 3)}{line}' for line in wrapped_value[1:])
            return output

        table_rows = [[value for _, value in row] for row in normalized_rows]
        if not table_rows:
            return []
        column_count = max(len(row) for row in table_rows)
        table_rows = [row + [''] * (column_count - len(row)) for row in table_rows]
        widths = [
            min(36, max(4, max(len(row[index]) for row in table_rows)))
            for index in range(column_count)
        ]
        separators = 3 * (column_count - 1)
        while sum(widths) + separators > max_width:
            widest = max(range(column_count), key=widths.__getitem__)
            if widths[widest] <= 8:
                break
            widths[widest] -= 1

        def format_row(row):
            wrapped_cells = [
                textwrap.wrap(value, width=widths[index]) or ['']
                for index, value in enumerate(row)
            ]
            row_height = max(len(cell_lines) for cell_lines in wrapped_cells)
            formatted_lines = []
            for line_index in range(row_height):
                cells = [
                    cell_lines[line_index] if line_index < len(cell_lines) else ''
                    for cell_lines in wrapped_cells
                ]
                formatted_lines.append(
                    ' | '.join(value.ljust(widths[index]) for index, value in enumerate(cells))
                )
            return formatted_lines

        output = []
        if has_header:
            output.extend(format_row(table_rows[0]))
            output.append('-+-'.join('-' * width for width in widths))
            for row in table_rows[1:]:
                output.extend(format_row(row))
        else:
            for row in table_rows:
                output.extend(format_row(row))
        return output


@contextmanager
def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def hash_password(password, salt=None):
    salt = salt or os.urandom(16)
    password_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    return salt.hex(), password_hash.hex()


def authenticate_user(username, password):
    with connect_db() as conn:
        user = conn.execute(
            'SELECT id, username, password_salt, password_hash, role FROM usuarios WHERE username = ?',
            (username.strip(),),
        ).fetchone()
    if user is None:
        return None
    _, candidate_hash = hash_password(password, bytes.fromhex(user['password_salt']))
    if not hmac.compare_digest(candidate_hash, user['password_hash']):
        return None
    return {'id': user['id'], 'username': user['username'], 'role': user['role']}


def init_db():
    with connect_db() as conn:
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('Administrador', 'Usuário')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS funcionarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                cargo TEXT NOT NULL,
                setor TEXT NOT NULL,
                salario REAL NOT NULL
            )
            '''
        )
        user_columns = {
            row['name'] for row in conn.execute('PRAGMA table_info(usuarios)')
        }
        if 'funcionario_id' not in user_columns:
            conn.execute(
                'ALTER TABLE usuarios ADD COLUMN funcionario_id INTEGER '
                'REFERENCES funcionarios(id) ON DELETE SET NULL'
            )
        conn.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_funcionario_id '
            'ON usuarios(funcionario_id)'
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS dependentes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                funcionario_id INTEGER NOT NULL,
                nome TEXT NOT NULL,
                parentesco TEXT NOT NULL,
                FOREIGN KEY(funcionario_id) REFERENCES funcionarios(id)
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS beneficios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                funcionario_id INTEGER NOT NULL,
                tipo TEXT NOT NULL,
                descricao TEXT NOT NULL,
                valor REAL NOT NULL CHECK (valor >= 0),
                data_inicio TEXT NOT NULL,
                ativo INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
                FOREIGN KEY(funcionario_id) REFERENCES funcionarios(id) ON DELETE CASCADE
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS avaliacoes_desempenho (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                funcionario_id INTEGER NOT NULL,
                avaliador_id INTEGER,
                nota REAL NOT NULL CHECK (nota >= 0 AND nota <= 10),
                comentarios TEXT NOT NULL DEFAULT '',
                data_avaliacao TEXT NOT NULL DEFAULT CURRENT_DATE,
                FOREIGN KEY(funcionario_id) REFERENCES funcionarios(id) ON DELETE CASCADE,
                FOREIGN KEY(avaliador_id) REFERENCES usuarios(id) ON DELETE SET NULL
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS contracheques (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                funcionario_id INTEGER NOT NULL,
                mes_ano TEXT NOT NULL,
                salario_bruto REAL NOT NULL,
                descontos REAL NOT NULL,
                salario_liquido REAL NOT NULL,
                FOREIGN KEY(funcionario_id) REFERENCES funcionarios(id)
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS ponto (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                funcionario_id INTEGER NOT NULL,
                data TEXT NOT NULL,
                entrada TEXT NOT NULL,
                saida TEXT NOT NULL,
                FOREIGN KEY(funcionario_id) REFERENCES funcionarios(id)
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS ferias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                funcionario_id INTEGER NOT NULL,
                inicio TEXT NOT NULL,
                fim TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Pendente',
                FOREIGN KEY(funcionario_id) REFERENCES funcionarios(id)
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS treinamentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL UNIQUE,
                categoria TEXT NOT NULL,
                carga_horaria INTEGER NOT NULL,
                modalidade TEXT NOT NULL
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS treinamento_inscricoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                treinamento_id INTEGER NOT NULL,
                funcionario_id INTEGER NOT NULL,
                UNIQUE (treinamento_id, funcionario_id),
                FOREIGN KEY(treinamento_id) REFERENCES treinamentos(id),
                FOREIGN KEY(funcionario_id) REFERENCES funcionarios(id)
            )
            '''
        )


def ensure_seed_data():
    with connect_db() as conn:
        if conn.execute('SELECT COUNT(*) FROM funcionarios').fetchone()[0] > 0:
            return

        dados = [
            ('Ana Souza', 'Analista de RH', 'Recursos Humanos', 4500.00),
            ('Carlos Eduardo', 'Desenvolvedor Senior', 'Tecnologia', 8500.00),
            ('Mariana Costa', 'Coordenadora de Vendas', 'Comercial', 6200.00),
            ('Lucas Mendes', 'Designer UX/UI', 'Tecnologia', 5200.00),
        ]
        conn.executemany(
            'INSERT INTO funcionarios (nome, cargo, setor, salario) VALUES (?, ?, ?, ?)',
            dados,
        )

        conn.execute(
            'INSERT INTO dependentes (funcionario_id, nome, parentesco) VALUES (?, ?, ?)',
            (1, 'Pedro Souza', 'Filho(a)'),
        )
        conn.execute(
            'INSERT INTO dependentes (funcionario_id, nome, parentesco) VALUES (?, ?, ?)',
            (2, 'Juliana Eduardo', 'Cônjuge'),
        )
        conn.execute(
            'INSERT INTO contracheques (funcionario_id, mes_ano, salario_bruto, descontos, salario_liquido) VALUES (?, ?, ?, ?, ?)',
            (1, '10/2026', 4500.00, 350.00, 4150.00),
        )
        conn.execute(
            'INSERT INTO ponto (funcionario_id, data, entrada, saida) VALUES (?, ?, ?, ?)',
            (2, '2026-10-25', '08:00', '17:00'),
        )
        conn.execute(
            'INSERT INTO ferias (funcionario_id, inicio, fim, status) VALUES (?, ?, ?, ?)',
            (1, '2026-11-10', '2026-11-24', 'Pendente'),
        )

def ensure_training_seed_data():
    with connect_db() as conn:
        conn.executemany(
            'INSERT OR IGNORE INTO treinamentos (titulo, categoria, carga_horaria, modalidade) VALUES (?, ?, ?, ?)',
            [
                ('Segurança e LGPD no Ambiente de Trabalho', 'Obrigatório', 10, 'EAD'),
                ('Gestão de Equipes High Performance', 'Liderança', 24, 'Presencial'),
                ('Atendimento ao Cliente e Service Recovery', 'Operacional', 12, 'EAD'),
                ('Compliance e Ética Corporativa', 'Estratégico', 8, 'Online'),
            ],
        )


class LoginDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.user = None
        with connect_db() as conn:
            self.first_run = conn.execute('SELECT COUNT(*) FROM usuarios').fetchone()[0] == 0

        self.title('Acesso - Sistema de Gestão Corporativo')
        self.geometry('440x390' if self.first_run else '440x320')
        self.resizable(False, False)
        self.configure(bg='#f3f4f6')
        self.protocol('WM_DELETE_WINDOW', self.cancel)

        card = tk.Frame(self, bg='white', padx=28, pady=24, bd=1, relief='solid')
        card.pack(fill='both', expand=True, padx=24, pady=24)
        heading = 'Criar administrador' if self.first_run else 'Entrar no sistema'
        tk.Label(
            card,
            text=heading,
            bg='white',
            fg='#0f172a',
            font=('Segoe UI', 17, 'bold'),
        ).pack(pady=(0, 6))
        description = (
            'Crie a primeira conta, que terá privilégios de administrador.'
            if self.first_run
            else 'Informe suas credenciais para continuar.'
        )
        tk.Label(
            card,
            text=description,
            bg='white',
            fg='#64748b',
            font=('Segoe UI', 9),
            wraplength=340,
        ).pack(pady=(0, 18))

        self.username_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.confirm_var = tk.StringVar()
        self.add_field(card, 'Usuário', self.username_var)
        self.add_field(card, 'Senha', self.password_var, show='*')
        if self.first_run:
            self.add_field(card, 'Confirmar senha', self.confirm_var, show='*')

        tk.Button(
            card,
            text='Criar conta e entrar' if self.first_run else 'Entrar',
            bg='#2563eb',
            fg='white',
            activebackground='#1d4ed8',
            activeforeground='white',
            font=('Segoe UI', 10, 'bold'),
            command=self.submit,
        ).pack(fill='x', pady=(16, 0), ipady=7)
        self.bind('<Return>', lambda _event: self.submit())
        self.grab_set()
        self.update_idletasks()
        x = (self.winfo_screenwidth() - self.winfo_width()) // 2
        y = (self.winfo_screenheight() - self.winfo_height()) // 2
        self.geometry(f'+{x}+{y}')
        self.focus_force()
        apply_widget_theme(self, APP_SETTINGS['theme'])

    @staticmethod
    def add_field(parent, label, variable, show=None):
        field = tk.Frame(parent, bg='white')
        field.pack(fill='x', pady=5)
        tk.Label(
            field,
            text=label,
            bg='white',
            fg='#334155',
            font=('Segoe UI', 9, 'bold'),
        ).pack(anchor='w')
        entry = tk.Entry(field, textvariable=variable, show=show, font=('Segoe UI', 11))
        entry.pack(fill='x', ipady=5, pady=(3, 0))
        return entry

    def submit(self):
        username = self.username_var.get().strip()
        password = self.password_var.get()
        if not username or not password:
            messagebox.showwarning('Dados obrigatórios', 'Informe o usuário e a senha.', parent=self)
            return

        if self.first_run:
            if len(password) < 8:
                messagebox.showwarning(
                    'Senha muito curta',
                    'A senha deve ter pelo menos 8 caracteres.',
                    parent=self,
                )
                return
            if password != self.confirm_var.get():
                messagebox.showwarning('Senhas diferentes', 'As senhas informadas não coincidem.', parent=self)
                return
            salt, password_hash = hash_password(password)
            try:
                with connect_db() as conn:
                    conn.execute('BEGIN IMMEDIATE')
                    if conn.execute('SELECT COUNT(*) FROM usuarios').fetchone()[0] != 0:
                        messagebox.showerror(
                            'Configuração concluída',
                            'A conta inicial já foi criada. Feche e abra o aplicativo para entrar.',
                            parent=self,
                        )
                        return
                    cursor = conn.execute(
                        'INSERT INTO usuarios (username, password_salt, password_hash, role) '
                        'VALUES (?, ?, ?, ?)',
                        (username, salt, password_hash, 'Administrador'),
                    )
                    self.user = {
                        'id': cursor.lastrowid,
                        'username': username,
                        'role': 'Administrador',
                    }
            except sqlite3.IntegrityError:
                messagebox.showerror('Usuário já existe', 'Escolha outro nome de usuário.', parent=self)
                return
        else:
            self.user = authenticate_user(username, password)
            if self.user is None:
                messagebox.showerror('Acesso negado', 'Usuário ou senha incorretos.', parent=self)
                return
        self.destroy()

    def cancel(self):
        self.user = None
        self.destroy()


class RHDesktopApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.theme = APP_SETTINGS['theme']
        self.title('Sistema de Gestão Corporativo')
        self.geometry('1200x760')
        self.minsize(1000, 700)
        self.configure(bg='#f3f4f6')
        self.withdraw()
        login = LoginDialog(self)
        self.wait_window(login)
        self.current_user = login.user
        if self.current_user is None:
            self.destroy()
            return
        self.deiconify()

        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('Treeview', font=('Segoe UI', 10), rowheight=28)
        style.configure('Treeview.Heading', font=('Segoe UI', 10, 'bold'))

        top = tk.Frame(self, bg='#ffffff', padx=20, pady=18)
        top.pack(fill='x', side='top')

        tk.Label(
            top,
            text='Sistema de Gestão Corporativo',
            bg='#ffffff',
            fg='#0f172a',
            font=('Segoe UI', 22, 'bold'),
        ).pack(fill='x', anchor='center')
        tk.Label(
            top,
            text='ERP Desktop RH • Módulo de Gestão de Pessoas',
            bg='#ffffff',
            fg='#64748b',
            font=('Segoe UI', 10),
        ).pack(fill='x', anchor='center', pady=(3, 0))

        summary = tk.Frame(self, bg='#f3f4f6', padx=20, pady=16)
        summary.pack(fill='x')
        self.kpis = {}
        cards = [
            ('Total Colaboradores', 'kpi_total_colaboradores'),
            ('Média Salarial', 'kpi_media_salarial'),
            ('Total Departamentos', 'kpi_total_deptos'),
            ('Férias Pendentes', 'kpi_ferias_pendentes'),
        ]
        for idx, (label, key) in enumerate(cards):
            card = tk.Frame(summary, bg='#ffffff', bd=1, relief='solid', padx=16, pady=14, width=220, height=90)
            card.grid(row=0, column=idx, padx=(0, 12) if idx < 3 else 0, sticky='nsew')
            card.grid_propagate(False)
            tk.Label(card, text=label, bg='#ffffff', fg='#64748b', font=('Segoe UI', 9, 'bold')).pack(anchor='w')
            value = tk.Label(card, text='0', bg='#ffffff', fg='#111827', font=('Segoe UI', 22, 'bold'))
            value.pack(anchor='w', pady=(8, 0))
            self.kpis[key] = value
        summary.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.editing_colaborador_id = None
        self.dep_editing_id = None
        self.cc_editing_id = None
        self.ponto_editing_id = None
        self.ferias_editing_id = None
        self.treinamento_editing_id = None
        self.selected_treinamento_id = None
        self.user_editing_id = None

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill='both', expand=True, padx=20, pady=(0, 20))

        self.notebook.add(self.build_colaborador_page(), text=' Colaboradores ')
        self.notebook.add(self.build_departamento_page(), text=' Departamentos ')
        self.notebook.add(self.build_cargo_page(), text=' Cargos ')
        self.notebook.add(self.build_dependente_page(), text=' Dependentes ')
        self.notebook.add(self.build_contracheque_page(), text=' Contracheques ')
        self.notebook.add(self.build_ponto_page(), text=' Ponto ')
        self.notebook.add(self.build_ferias_page(), text=' Férias ')
        self.notebook.add(self.build_treinamentos_page(), text=' Treinamentos ')
        if self.current_user['role'] == 'Administrador':
            self.notebook.add(self.build_users_page(), text=' Usuários ')
        self.notebook.add(self.build_settings_page(), text=' Configurações ')

        self.configure_theme_styles()
        apply_widget_theme(self, self.theme)
        self.load_all_data()

    def configure_theme_styles(self):
        dark = self.theme == 'dark'
        background = '#0f172a' if dark else '#f3f4f6'
        surface = '#1e293b' if dark else '#ffffff'
        foreground = '#f1f5f9' if dark else '#0f172a'
        secondary = '#94a3b8' if dark else '#64748b'
        border = '#334155' if dark else '#e2e8f0'
        style = ttk.Style(self)
        style.configure('TFrame', background=background)
        style.configure('TLabel', background=background, foreground=foreground)
        style.configure('TButton', background=surface, foreground=foreground)
        style.map(
            'TButton',
            background=[('active', border), ('disabled', background)],
            foreground=[('disabled', secondary)],
        )
        style.configure('TNotebook', background=background, borderwidth=0)
        style.configure(
            'TNotebook.Tab',
            background=border,
            foreground=foreground,
            padding=(12, 7),
        )
        style.map(
            'TNotebook.Tab',
            background=[('selected', surface), ('active', background)],
            foreground=[('selected', foreground)],
        )
        style.configure(
            'TEntry',
            fieldbackground=surface,
            foreground=foreground,
            insertcolor=foreground,
        )
        style.configure(
            'TCombobox',
            fieldbackground=surface,
            background=surface,
            foreground=foreground,
            arrowcolor=foreground,
        )
        style.map(
            'TCombobox',
            fieldbackground=[('readonly', surface)],
            foreground=[('readonly', foreground)],
            selectbackground=[('readonly', surface)],
            selectforeground=[('readonly', foreground)],
        )
        style.configure(
            'Treeview',
            background=surface,
            fieldbackground=surface,
            foreground=foreground,
            font=('Segoe UI', 10),
            rowheight=28,
        )
        style.map(
            'Treeview',
            background=[('selected', '#2563eb')],
            foreground=[('selected', 'white')],
        )
        style.configure(
            'Treeview.Heading',
            background=border,
            foreground=foreground,
            font=('Segoe UI', 10, 'bold'),
        )
        style.map('Treeview.Heading', background=[('active', background)])
        style.configure('TScrollbar', background=border, troughcolor=background)

    def build_settings_page(self):
        page = ttk.Frame(self.notebook, padding=16)
        panel = tk.Frame(page, bg='white', padx=24, pady=24, bd=1, relief='solid')
        panel.pack(fill='both', expand=True, anchor='n')
        tk.Label(
            panel,
            text='Configurações do aplicativo',
            bg='white',
            fg='#0f172a',
            font=('Segoe UI', 16, 'bold'),
        ).pack(anchor='w')

        theme_section = tk.Frame(panel, bg='white')
        theme_section.pack(fill='x', pady=(24, 0))
        tk.Label(
            theme_section,
            text='Tema',
            bg='white',
            fg='#0f172a',
            font=('Segoe UI', 12, 'bold'),
        ).pack(anchor='w')
        tk.Label(
            theme_section,
            text='Escolha a aparência do sistema.',
            bg='white',
            fg='#64748b',
        ).pack(anchor='w', pady=(4, 8))
        self.theme_var = tk.StringVar(value=self.theme)
        theme_options = tk.Frame(theme_section, bg='white')
        theme_options.pack(anchor='w')
        for label, value in (('Claro', 'light'), ('Escuro', 'dark')):
            tk.Radiobutton(
                theme_options,
                text=label,
                variable=self.theme_var,
                value=value,
                bg='white',
                fg='#334155',
                activebackground='white',
                command=self.change_theme,
            ).pack(side='left', padx=(0, 16))

        database_section = tk.Frame(panel, bg='white')
        database_section.pack(fill='x', pady=(28, 0))
        tk.Label(
            database_section,
            text='Pasta do banco de dados',
            bg='white',
            fg='#0f172a',
            font=('Segoe UI', 12, 'bold'),
        ).pack(anchor='w')
        if self.current_user['role'] != 'Administrador':
            tk.Label(
                database_section,
                text='Somente administradores podem alterar a pasta do banco.',
                bg='white',
                fg='#64748b',
            ).pack(anchor='w', pady=(6, 0))
        else:
            tk.Label(
                database_section,
                text='A alteração será usada na próxima vez que o aplicativo for iniciado. '
                'Os dados não serão movidos ou copiados.',
                bg='white',
                fg='#64748b',
                wraplength=760,
                justify='left',
            ).pack(anchor='w', pady=(6, 10))
            self.database_directory_var = tk.StringVar(
                value=APP_SETTINGS['database_directory'] or str(DB_DIR)
            )
            folder_controls = tk.Frame(database_section, bg='white')
            folder_controls.pack(fill='x')
            tk.Entry(
                folder_controls,
                textvariable=self.database_directory_var,
                state='readonly',
                font=('Segoe UI', 10),
            ).pack(side='left', fill='x', expand=True, padx=(0, 8))
            tk.Button(
                folder_controls,
                text='Escolher pasta',
                command=self.choose_database_directory,
            ).pack(side='left')
            tk.Button(
                folder_controls,
                text='Usar padrão do sistema',
                command=self.use_default_database_directory,
            ).pack(side='left', padx=(8, 0))
            tk.Label(
                database_section,
                text=f'Arquivo do banco: {DB_PATH.name}',
                bg='white',
                fg='#64748b',
            ).pack(anchor='w', pady=(8, 0))
            self.database_settings_status = tk.Label(
                database_section,
                text='',
                bg='white',
                fg='#065f46',
                wraplength=760,
                justify='left',
            )
            self.database_settings_status.pack(anchor='w', pady=(8, 0))
        return page

    def change_theme(self):
        global APP_SETTINGS
        selected_theme = self.theme_var.get()
        updated_settings = {**APP_SETTINGS, 'theme': selected_theme}
        try:
            save_app_settings(updated_settings)
        except OSError as exc:
            self.theme_var.set(self.theme)
            messagebox.showerror(
                'Não foi possível salvar',
                f'As configurações do tema não puderam ser salvas:\n{exc}',
                parent=self,
            )
            return
        APP_SETTINGS = updated_settings
        self.theme = selected_theme
        self.configure_theme_styles()
        apply_widget_theme(self, self.theme)

    def choose_database_directory(self):
        selected_directory = filedialog.askdirectory(
            parent=self,
            initialdir=self.database_directory_var.get(),
            mustexist=True,
            title='Escolha a pasta do banco de dados',
        )
        if selected_directory:
            self.database_directory_var.set(selected_directory)
            self.save_database_directory(selected_directory)

    def use_default_database_directory(self):
        self.database_directory_var.set(str(DB_DIR))
        self.save_database_directory(None)

    def save_database_directory(self, directory):
        global APP_SETTINGS
        if self.current_user['role'] != 'Administrador':
            return
        if directory is not None:
            directory = str(Path(directory).expanduser().resolve())
            if not Path(directory).is_dir():
                messagebox.showerror(
                    'Pasta inválida',
                    'Selecione uma pasta existente para o banco de dados.',
                    parent=self,
                )
                return
        updated_settings = {**APP_SETTINGS, 'database_directory': directory}
        try:
            save_app_settings(updated_settings)
        except OSError as exc:
            messagebox.showerror(
                'Não foi possível salvar',
                f'A pasta do banco de dados não pôde ser salva:\n{exc}',
                parent=self,
            )
            return
        APP_SETTINGS = updated_settings
        selected_path = database_path_for_settings(APP_SETTINGS)
        self.database_settings_status.configure(
            text=f'Pasta salva. O banco em {selected_path} será usado na próxima inicialização.'
        )

    def create_print_button(self, parent, title, tree):
        return tk.Button(
            parent,
            text='Imprimir Relação',
            bg='#0f766e',
            fg='white',
            font=('Segoe UI', 10, 'bold'),
            command=lambda: self.imprimir_relacao(title, tree),
        )

    def create_print_selected_button(self, parent, title, tree):
        return tk.Button(
            parent,
            text='Imprimir Selecionado',
            bg='#0369a1',
            fg='white',
            font=('Segoe UI', 10, 'bold'),
            command=lambda: self.imprimir_relacao(title, tree, selected_only=True),
        )

    def imprimir_relacao(self, title, tree, selected_only=False):
        if selected_only:
            selected_items = tree.selection()
            if not selected_items:
                messagebox.showwarning(
                    'Nenhum registro selecionado',
                    'Selecione um registro para imprimir individualmente.',
                )
                return
            self.imprimir_registro_individual(title, tree, selected_items[0])
            return

        all_columns = list(tree['columns'])
        display_columns = tree['displaycolumns']
        if display_columns == '#all' or display_columns == ('#all',) or display_columns == ['#all']:
            display_columns = all_columns
        else:
            if isinstance(display_columns, str):
                display_columns = tree.tk.splitlist(display_columns)
            display_columns = list(display_columns)

        visible_columns = [
            column
            for column in display_columns
            if column in all_columns
            and tree.heading(column, 'text')
            and int(tree.column(column, 'width')) > 0
        ]
        column_indexes = {column: all_columns.index(column) for column in visible_columns}
        headers = [tree.heading(column, 'text') for column in visible_columns]

        table_rows = []
        for item_id in tree.get_children():
            values = tree.item(item_id, 'values')
            table_rows.append([values[column_indexes[column]] for column in visible_columns])

        header_html = ''.join(f'<th>{html.escape(str(header))}</th>' for header in headers)
        rows_html = ''.join(
            '<tr>' + ''.join(f'<td>{html.escape(str(value))}</td>' for value in row) + '</tr>'
            for row in table_rows
        )
        if not table_rows:
            rows_html = f'<tr><td colspan="{max(1, len(headers))}">Nenhum registro encontrado.</td></tr>'

        body_html = f"""<table>
<thead><tr>{header_html}</tr></thead>
<tbody>{rows_html}</tbody>
</table>"""
        self.abrir_relatorio_html(title, body_html)

    def imprimir_registro_individual(self, title, tree, item_id):
        record_id = tree.item(item_id, 'values')[0]
        with connect_db() as conn:
            if title == 'Relação de Treinamentos':
                course = conn.execute(
                    'SELECT id, titulo, categoria, carga_horaria, modalidade FROM treinamentos WHERE id = ?',
                    (record_id,),
                ).fetchone()
                if course is None:
                    messagebox.showerror('Registro não encontrado', 'Não foi possível localizar este treinamento.')
                    return
                participants = conn.execute(
                    'SELECT f.nome, f.cargo, f.setor FROM treinamento_inscricoes ti JOIN funcionarios f ON f.id = ti.funcionario_id WHERE ti.treinamento_id = ? ORDER BY f.nome',
                    (course['id'],),
                ).fetchall()
                report_title = f'Treinamento - {course["titulo"]}'
                details_html = self.html_details([
                    ('Treinamento', course['titulo']),
                    ('Categoria', course['categoria']),
                    ('Carga horária', f'{course["carga_horaria"]} horas'),
                    ('Modalidade', course['modalidade']),
                ])
                participant_values = [
                    (row['nome'], row['cargo'], row['setor'])
                    for row in participants
                ]
                body_html = (
                    f'<h2>Dados do treinamento</h2>{details_html}'
                    f'<h2>Colaboradores inscritos</h2>'
                    f'{self.html_table(("Colaborador", "Cargo", "Setor"), participant_values)}'
                )

            elif title == 'Relação de Dependentes':
                employee = conn.execute(
                    'SELECT f.id, f.nome, f.cargo, f.setor FROM dependentes d JOIN funcionarios f ON f.id = d.funcionario_id WHERE d.id = ?',
                    (record_id,),
                ).fetchone()
                if employee is None:
                    messagebox.showerror('Registro não encontrado', 'Não foi possível localizar o colaborador deste dependente.')
                    return
                rows = conn.execute(
                    'SELECT nome, parentesco FROM dependentes WHERE funcionario_id = ? ORDER BY nome',
                    (employee['id'],),
                ).fetchall()
                report_title = 'Relação de Dependentes'
                details_html = self.html_details([
                    ('Colaborador', employee['nome']),
                    ('Cargo', employee['cargo']),
                    ('Setor', employee['setor']),
                ])
                headers = ('Nome do Dependente', 'Parentesco')
                values = [(row['nome'], row['parentesco']) for row in rows]
                body_html = f'<h2>Colaborador</h2>{details_html}<h2>Dependentes</h2>{self.html_table(headers, values)}'

            elif title == 'Relação de Contracheques':
                row = conn.execute(
                    'SELECT c.mes_ano, c.salario_bruto, c.descontos, c.salario_liquido, f.nome, f.cargo, f.setor FROM contracheques c JOIN funcionarios f ON f.id = c.funcionario_id WHERE c.id = ?',
                    (record_id,),
                ).fetchone()
                if row is None:
                    messagebox.showerror('Registro não encontrado', 'Não foi possível localizar este contracheque.')
                    return
                report_title = f'Contracheque - {row["mes_ano"]}'
                details_html = self.html_details([
                    ('Colaborador', row['nome']),
                    ('Cargo', row['cargo']),
                    ('Setor', row['setor']),
                    ('Competência', row['mes_ano']),
                ])
                values = [
                    ('Salário bruto', self.format_currency(row['salario_bruto'])),
                    ('Descontos totais', self.format_currency(row['descontos'])),
                    ('Salário líquido', self.format_currency(row['salario_liquido'])),
                ]
                body_html = f'<h2>Identificação</h2>{details_html}<h2>Demonstrativo</h2>{self.html_table(("Descrição", "Valor"), values)}'

            elif title == 'Relação de Ponto':
                selected_row = conn.execute(
                    'SELECT p.funcionario_id, p.data, f.nome, f.cargo, f.setor FROM ponto p JOIN funcionarios f ON f.id = p.funcionario_id WHERE p.id = ?',
                    (record_id,),
                ).fetchone()
                if selected_row is None:
                    messagebox.showerror('Registro não encontrado', 'Não foi possível localizar este registro de ponto.')
                    return
                month_key = self.ponto_month_key(selected_row['data'])
                if not month_key:
                    messagebox.showerror(
                        'Data inválida',
                        'A data do registro selecionado não permite identificar o mês de referência.',
                    )
                    return
                all_rows = conn.execute(
                    'SELECT data, entrada, saida FROM ponto WHERE funcionario_id = ? ORDER BY data, entrada',
                    (selected_row['funcionario_id'],),
                ).fetchall()
                rows = [row for row in all_rows if self.ponto_month_key(row['data']) == month_key]
                month_label = month_key.replace('-', '/') if month_key else selected_row['data']
                report_title = f'Registros de Ponto - {month_label}'
                details_html = self.html_details([
                    ('Colaborador', selected_row['nome']),
                    ('Cargo', selected_row['cargo']),
                    ('Setor', selected_row['setor']),
                    ('Mês de referência', month_label),
                ])
                values = [
                    (self.format_date(row['data']), row['entrada'], row['saida'])
                    for row in rows
                ]
                body_html = f'<h2>Colaborador</h2>{details_html}<h2>Marcações do mês</h2>{self.html_table(("Data", "Entrada", "Saída"), values)}'

            elif title == 'Relação de Férias':
                row = conn.execute(
                    'SELECT fr.inicio, fr.fim, fr.status, f.nome, f.cargo, f.setor FROM ferias fr JOIN funcionarios f ON f.id = fr.funcionario_id WHERE fr.id = ?',
                    (record_id,),
                ).fetchone()
                if row is None:
                    messagebox.showerror('Registro não encontrado', 'Não foi possível localizar este aviso de férias.')
                    return
                report_title = 'Aviso de Férias'
                details_html = self.html_details([
                    ('Colaborador', row['nome']),
                    ('Cargo', row['cargo']),
                    ('Setor', row['setor']),
                    ('Início das férias', self.format_date(row['inicio'])),
                    ('Término das férias', self.format_date(row['fim'])),
                    ('Status', row['status']),
                ])
                body_html = f"""{details_html}
<p class="notice">Comunicamos a concessão do período de férias acima informado.</p>
<div class="signatures">
    <div>____________________________________<br>Assinatura do colaborador</div>
    <div>____________________________________<br>Responsável pela empresa</div>
</div>"""
            else:
                messagebox.showerror('Impressão individual indisponível', 'Este tipo de relação não possui impressão individual.')
                return

        self.abrir_relatorio_html(report_title, body_html)

    @staticmethod
    def html_details(details):
        return '<table class="details">' + ''.join(
            f'<tr><th>{html.escape(str(label))}</th><td>{html.escape(str(value))}</td></tr>'
            for label, value in details
        ) + '</table>'

    @staticmethod
    def html_table(headers, rows):
        header_html = ''.join(f'<th>{html.escape(str(header))}</th>' for header in headers)
        if rows:
            rows_html = ''.join(
                '<tr>' + ''.join(f'<td>{html.escape(str(value))}</td>' for value in row) + '</tr>'
                for row in rows
            )
        else:
            rows_html = f'<tr><td colspan="{len(headers)}">Nenhum registro encontrado.</td></tr>'
        return f'<table><thead><tr>{header_html}</tr></thead><tbody>{rows_html}</tbody></table>'

    @staticmethod
    def format_currency(value):
        return f'R$ {float(value or 0):,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')

    @staticmethod
    def format_date(value):
        for date_format in ('%Y-%m-%d', '%d/%m/%Y', '%Y-%m'):
            try:
                parsed = datetime.strptime(str(value), date_format)
                return parsed.strftime('%m/%Y') if date_format == '%Y-%m' else parsed.strftime('%d/%m/%Y')
            except ValueError:
                continue
        return str(value)

    @staticmethod
    def ponto_month_key(value):
        for date_format in ('%Y-%m-%d', '%d/%m/%Y', '%Y-%m', '%m/%Y'):
            try:
                parsed = datetime.strptime(str(value), date_format)
                return parsed.strftime('%Y-%m')
            except ValueError:
                continue
        return ''

    def abrir_relatorio_html(self, title, body_html):
        report_html = f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
    body {{ font-family: Arial, sans-serif; color: #1f2937; margin: 28px; }}
    h1 {{ font-size: 20px; margin-bottom: 6px; }}
    h2 {{ font-size: 15px; margin: 22px 0 8px; }}
    p {{ color: #64748b; font-size: 12px; margin-top: 0; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 18px; }}
    th, td {{ border: 1px solid #cbd5e1; padding: 8px; text-align: left; }}
    th {{ background: #e2e8f0; }}
    tr:nth-child(even) {{ background: #f8fafc; }}
    .details th {{ width: 28%; }}
    .notice {{ margin-top: 30px; font-size: 14px; }}
    .signatures {{ display: flex; justify-content: space-between; gap: 40px; margin-top: 70px; text-align: center; }}
    .signatures div {{ width: 48%; }}
    @media print {{ body {{ margin: 12mm; }} }}
</style>
</head>
<body>
<h1>{html.escape(title)}</h1>
<p>Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
{body_html}
<script>window.addEventListener('load', () => window.print());</script>
</body>
</html>
"""
        parser = ReportTextParser()
        parser.feed(report_html)
        lines = parser.get_lines()
        if not lines:
            messagebox.showerror('Relatório vazio', 'Não há conteúdo para enviar à impressão.')
            return

        self.abrir_visualizacao_impressao(title, lines)

    def abrir_visualizacao_impressao(self, title, lines):
        preview = tk.Toplevel(self)
        preview.title(f'Visualização de impressão - {title}')
        preview.geometry('850x720')
        preview.minsize(600, 450)
        preview.transient(self)

        toolbar = ttk.Frame(preview, padding=(12, 10))
        toolbar.pack(fill='x')
        ttk.Label(
            toolbar,
            text='Visualização de impressão',
            font=('Segoe UI', 12, 'bold'),
        ).pack(side='left')
        ttk.Button(
            toolbar,
            text='Imprimir...',
            command=lambda: self.imprimir_visualizacao(preview, title, lines),
        ).pack(side='right')
        ttk.Button(
            toolbar,
            text='Fechar',
            command=preview.destroy,
        ).pack(side='right', padx=(0, 8))

        page_area = tk.Frame(preview, bg='#d1d5db', padx=24, pady=24)
        page_area.pack(fill='both', expand=True)
        paper = tk.Frame(page_area, bg='white', padx=48, pady=40, bd=1, relief='solid')
        paper.pack(fill='both', expand=True)

        text_frame = ttk.Frame(paper)
        text_frame.pack(fill='both', expand=True)
        scrollbar = ttk.Scrollbar(text_frame, orient='vertical')
        document = tk.Text(
            text_frame,
            wrap='word',
            font=('Courier New', 10),
            bg='white',
            fg='#111827',
            relief='flat',
            padx=4,
            pady=4,
            state='normal',
            yscrollcommand=scrollbar.set,
        )
        scrollbar.config(command=document.yview)
        scrollbar.pack(side='right', fill='y')
        document.pack(side='left', fill='both', expand=True)
        document.insert('1.0', '\n'.join(lines))
        document.config(state='disabled')
        preview.grab_set()

    def imprimir_visualizacao(self, preview, title, lines):
        preview.grab_release()
        preview.withdraw()
        try:
            self.imprimir_texto_windows(title, lines)
        except (OSError, AttributeError, ctypes.ArgumentError) as exc:
            messagebox.showerror('Erro ao imprimir', f'Não foi possível abrir o gerenciador de impressão:\n{exc}')
        finally:
            if preview.winfo_exists():
                preview.deiconify()
                preview.lift()
                preview.grab_set()

    def imprimir_texto_windows(self, title, lines):
        if os.name != 'nt':
            raise OSError('A impressão pelo diálogo nativo está disponível apenas no Windows.')

        from ctypes import wintypes

        class PrintDialog(ctypes.Structure):
            _fields_ = [
                ('lStructSize', wintypes.DWORD),
                ('hwndOwner', wintypes.HWND),
                ('hDevMode', wintypes.HANDLE),
                ('hDevNames', wintypes.HANDLE),
                ('hDC', wintypes.HANDLE),
                ('Flags', wintypes.DWORD),
                ('nFromPage', wintypes.WORD),
                ('nToPage', wintypes.WORD),
                ('nMinPage', wintypes.WORD),
                ('nMaxPage', wintypes.WORD),
                ('nCopies', wintypes.WORD),
                ('hInstance', wintypes.HINSTANCE),
                ('lCustData', wintypes.LPARAM),
                ('lpfnPrintHook', ctypes.c_void_p),
                ('lpfnSetupHook', ctypes.c_void_p),
                ('lpPrintTemplateName', wintypes.LPCWSTR),
                ('lpSetupTemplateName', wintypes.LPCWSTR),
                ('hPrintTemplate', wintypes.HANDLE),
                ('hSetupTemplate', wintypes.HANDLE),
            ]

        class DocInfo(ctypes.Structure):
            _fields_ = [
                ('cbSize', ctypes.c_int),
                ('lpszDocName', wintypes.LPCWSTR),
                ('lpszOutput', wintypes.LPCWSTR),
                ('lpszDatatype', wintypes.LPCWSTR),
                ('fwType', wintypes.DWORD),
            ]

        class TextMetric(ctypes.Structure):
            _fields_ = [
                ('tmHeight', ctypes.c_long),
                ('tmAscent', ctypes.c_long),
                ('tmDescent', ctypes.c_long),
                ('tmInternalLeading', ctypes.c_long),
                ('tmExternalLeading', ctypes.c_long),
                ('tmAveCharWidth', ctypes.c_long),
                ('tmMaxCharWidth', ctypes.c_long),
                ('tmWeight', ctypes.c_long),
                ('tmOverhang', ctypes.c_long),
                ('tmDigitizedAspectX', ctypes.c_long),
                ('tmDigitizedAspectY', ctypes.c_long),
                ('tmFirstChar', wintypes.WCHAR),
                ('tmLastChar', wintypes.WCHAR),
                ('tmDefaultChar', wintypes.WCHAR),
                ('tmBreakChar', wintypes.WCHAR),
                ('tmItalic', wintypes.BYTE),
                ('tmUnderlined', wintypes.BYTE),
                ('tmStruckOut', wintypes.BYTE),
                ('tmPitchAndFamily', wintypes.BYTE),
                ('tmCharSet', wintypes.BYTE),
            ]

        dialog = PrintDialog()
        dialog.lStructSize = ctypes.sizeof(PrintDialog)
        dialog.hwndOwner = self.winfo_id()
        dialog.Flags = 0x00000100 | 0x00000008 | 0x00000004
        dialog.nFromPage = 1
        dialog.nToPage = 1
        dialog.nMinPage = 1
        dialog.nMaxPage = 65535

        common_dialog = ctypes.WinDLL('comdlg32', use_last_error=True)
        common_dialog.PrintDlgW.argtypes = [ctypes.POINTER(PrintDialog)]
        common_dialog.PrintDlgW.restype = wintypes.BOOL
        common_dialog.CommDlgExtendedError.restype = wintypes.DWORD
        if not common_dialog.PrintDlgW(ctypes.byref(dialog)):
            error_code = common_dialog.CommDlgExtendedError()
            if error_code:
                raise OSError(error_code, 'Falha ao abrir o diálogo de impressão do Windows.')
            return

        gdi = ctypes.WinDLL('gdi32', use_last_error=True)
        gdi.CreateFontW.restype = wintypes.HANDLE
        gdi.CreateFontW.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
            wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
            wintypes.LPCWSTR,
        ]
        gdi.SelectObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        gdi.SelectObject.restype = wintypes.HANDLE
        gdi.GetDeviceCaps.argtypes = [wintypes.HANDLE, ctypes.c_int]
        gdi.GetDeviceCaps.restype = ctypes.c_int
        gdi.GetTextMetricsW.argtypes = [wintypes.HANDLE, ctypes.POINTER(TextMetric)]
        gdi.GetTextMetricsW.restype = wintypes.BOOL
        gdi.GetTextExtentPoint32W.argtypes = [
            wintypes.HANDLE, wintypes.LPCWSTR, ctypes.c_int, ctypes.c_void_p,
        ]
        gdi.GetTextExtentPoint32W.restype = wintypes.BOOL
        gdi.TextOutW.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_int, wintypes.LPCWSTR, ctypes.c_int,
        ]
        gdi.TextOutW.restype = wintypes.BOOL
        gdi.DeleteObject.argtypes = [wintypes.HANDLE]
        gdi.DeleteObject.restype = wintypes.BOOL
        gdi.DeleteDC.argtypes = [wintypes.HANDLE]
        gdi.DeleteDC.restype = wintypes.BOOL
        gdi.StartDocW.argtypes = [wintypes.HANDLE, ctypes.POINTER(DocInfo)]
        gdi.StartDocW.restype = ctypes.c_int
        gdi.StartPage.argtypes = [wintypes.HANDLE]
        gdi.StartPage.restype = ctypes.c_int
        gdi.EndPage.argtypes = [wintypes.HANDLE]
        gdi.EndPage.restype = ctypes.c_int
        gdi.EndDoc.argtypes = [wintypes.HANDLE]
        gdi.EndDoc.restype = ctypes.c_int
        gdi.AbortDoc.argtypes = [wintypes.HANDLE]
        gdi.AbortDoc.restype = ctypes.c_int
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GlobalFree.argtypes = [wintypes.HANDLE]
        kernel.GlobalFree.restype = wintypes.HANDLE

        printer_dc = dialog.hDC
        font_handle = None
        previous_font = None
        document_started = False
        try:
            dpi_x = gdi.GetDeviceCaps(printer_dc, 88)
            dpi_y = gdi.GetDeviceCaps(printer_dc, 90)
            page_width = gdi.GetDeviceCaps(printer_dc, 8)
            page_height = gdi.GetDeviceCaps(printer_dc, 10)
            left_margin = max(1, round(dpi_x * 0.5))
            top_margin = max(1, round(dpi_y * 0.5))
            font_height = -max(1, round(dpi_y * 10 / 72))
            font_handle = gdi.CreateFontW(
                font_height, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0, 'Arial',
            )
            if not font_handle:
                raise ctypes.WinError(ctypes.get_last_error())
            previous_font = gdi.SelectObject(printer_dc, font_handle)
            metrics = TextMetric()
            if not gdi.GetTextMetricsW(printer_dc, ctypes.byref(metrics)):
                raise ctypes.WinError(ctypes.get_last_error())

            class Size(ctypes.Structure):
                _fields_ = [('cx', ctypes.c_long), ('cy', ctypes.c_long)]

            def measure(text):
                extent = Size()
                if not gdi.GetTextExtentPoint32W(printer_dc, text, len(text), ctypes.byref(extent)):
                    raise ctypes.WinError(ctypes.get_last_error())
                return extent.cx

            max_text_width = max(1, page_width - (left_margin * 2))
            wrapped_lines = []
            for source_line in lines:
                current = ''
                for word in source_line.split():
                    candidate = f'{current} {word}'.strip()
                    if current and measure(candidate) > max_text_width:
                        wrapped_lines.append(current)
                        current = word
                    else:
                        current = candidate
                    while current and measure(current) > max_text_width:
                        split_at = max(1, len(current) - 1)
                        while split_at > 1 and measure(current[:split_at]) > max_text_width:
                            split_at -= 1
                        wrapped_lines.append(current[:split_at])
                        current = current[split_at:]
                if current:
                    wrapped_lines.append(current)
                elif not source_line.strip():
                    wrapped_lines.append('')

            line_height = max(1, metrics.tmHeight + metrics.tmExternalLeading)
            lines_per_page = max(1, (page_height - top_margin * 2) // line_height)
            doc_info = DocInfo()
            doc_info.cbSize = ctypes.sizeof(DocInfo)
            doc_info.lpszDocName = title
            if gdi.StartDocW(printer_dc, ctypes.byref(doc_info)) <= 0:
                raise ctypes.WinError(ctypes.get_last_error())
            document_started = True

            for index, line in enumerate(wrapped_lines):
                if index % lines_per_page == 0:
                    if gdi.StartPage(printer_dc) <= 0:
                        raise ctypes.WinError(ctypes.get_last_error())
                if line and not gdi.TextOutW(
                    printer_dc,
                    left_margin,
                    top_margin + (index % lines_per_page) * line_height,
                    line,
                    len(line),
                ):
                    raise ctypes.WinError(ctypes.get_last_error())
                if index % lines_per_page == lines_per_page - 1 or index == len(wrapped_lines) - 1:
                    if gdi.EndPage(printer_dc) <= 0:
                        raise ctypes.WinError(ctypes.get_last_error())

            if gdi.EndDoc(printer_dc) <= 0:
                raise ctypes.WinError(ctypes.get_last_error())
            document_started = False
        except Exception:
            if document_started:
                gdi.AbortDoc(printer_dc)
            raise
        finally:
            if previous_font:
                gdi.SelectObject(printer_dc, previous_font)
            if font_handle:
                gdi.DeleteObject(font_handle)
            gdi.DeleteDC(printer_dc)
            if dialog.hDevMode:
                kernel.GlobalFree(dialog.hDevMode)
            if dialog.hDevNames:
                kernel.GlobalFree(dialog.hDevNames)

    def build_colaborador_page(self):
        page = ttk.Frame(self.notebook, padding=16)
        left = tk.Frame(page, bg='#ffffff', pady=14, padx=14, bd=1, relief='solid')
        left.pack(side='left', fill='y', padx=(0, 12), ipadx=8, ipady=8)

        tk.Label(left, text='Novo Colaborador', font=('Segoe UI', 14, 'bold'), bg='#ffffff', fg='#0f172a').pack(anchor='w', pady=(0, 12))
        self.colab_vars = {}
        for label, key in [('Nome', 'nome'), ('Cargo', 'cargo'), ('Departamento / Setor', 'setor'), ('Salário Bruto (R$)', 'salario')]:
            tk.Label(left, text=label, bg='#ffffff', fg='#475569', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(10, 4))
            var = tk.StringVar()
            tk.Entry(left, textvariable=var, width=32, font=('Segoe UI', 10), bd=1, relief='solid').pack(fill='x', pady=(0, 8))
            self.colab_vars[key] = var

        save_frame = tk.Frame(left, bg='#ffffff')
        save_frame.pack(fill='x', pady=(8, 0))
        self.colab_save_btn = tk.Button(
            save_frame,
            text='Cadastrar Colaborador',
            bg='#4f46e5',
            fg='white',
            font=('Segoe UI', 10, 'bold'),
            command=self.cadastrar_colaborador,
        )
        self.colab_save_btn.pack(fill='x')
        self.colab_cancel_btn = tk.Button(
            save_frame,
            text='Cancelar Edição',
            bg='#e2e8f0',
            fg='#0f172a',
            font=('Segoe UI', 10, 'bold'),
            command=self.cancelar_edicao_colaborador,
            state='disabled',
        )
        self.colab_cancel_btn.pack(fill='x', pady=(8, 0))

        right = tk.Frame(page, bg='#ffffff', bd=1, relief='solid', padx=12, pady=12)
        right.pack(fill='both', expand=True)
        header = tk.Frame(right, bg='#ffffff')
        header.pack(fill='x')
        tk.Label(header, text='Quadro de Colaboradores', bg='#ffffff', fg='#0f172a', font=('Segoe UI', 14, 'bold')).pack(side='left')
        self.colaborador_total = tk.Label(header, text='0 Registros', bg='#e2e8f0', fg='#334155', font=('Segoe UI', 9, 'bold'))
        self.colaborador_total.pack(side='right', padx=8)

        self.colab_tree = ttk.Treeview(right, columns=('ID', 'Nome', 'Cargo', 'Setor', 'Salário'), show='headings')
        self.colab_tree.column('ID', width=0, stretch=False)
        self.colab_tree.heading('ID', text='')
        for col in ('Nome', 'Cargo', 'Setor', 'Salário'):
            self.colab_tree.heading(col, text=col)
            self.colab_tree.column(col, anchor='center', width=200)
        self.colab_tree.pack(fill='both', expand=True, pady=(12, 0))

        action = tk.Frame(right, bg='#ffffff')
        action.pack(fill='x', pady=(10, 0))
        self.create_print_button(action, 'Relação de Colaboradores', self.colab_tree).pack(side='left')
        tk.Button(
            action,
            text='Editar Selecionado',
            bg='#f59e0b',
            fg='white',
            font=('Segoe UI', 10, 'bold'),
            command=self.editar_colaborador,
        ).pack(side='left')
        tk.Button(
            action,
            text='Remover Selecionado',
            bg='#ef4444',
            fg='white',
            font=('Segoe UI', 10, 'bold'),
            command=self.remover_colaborador,
        ).pack(side='right')
        return page

    def build_departamento_page(self):
        page = ttk.Frame(self.notebook, padding=16)
        container = tk.Frame(page, bg='#ffffff', bd=1, relief='solid', padx=20, pady=20)
        container.pack(fill='both', expand=True)
        tk.Label(container, text='Departamentos Cadastrados', bg='#ffffff', fg='#0f172a', font=('Segoe UI', 15, 'bold')).pack(anchor='w')
        self.dept_tree = ttk.Treeview(container, columns=('Departamento', 'Colaboradores', 'Média Salarial'), show='headings')
        for col, width in [('Departamento', 280), ('Colaboradores', 140), ('Média Salarial', 220)]:
            self.dept_tree.heading(col, text=col)
            self.dept_tree.column(col, width=width, anchor='center' if col != 'Departamento' else 'w')
        toolbar = tk.Frame(container, bg='#ffffff')
        toolbar.pack(fill='x', pady=(10, 0))
        self.create_print_button(toolbar, 'Relação de Departamentos', self.dept_tree).pack(side='right')
        self.dept_tree.pack(fill='both', expand=True, pady=(12, 0))
        return page

    def build_cargo_page(self):
        page = ttk.Frame(self.notebook, padding=16)
        container = tk.Frame(page, bg='#ffffff', bd=1, relief='solid', padx=20, pady=20)
        container.pack(fill='both', expand=True)
        tk.Label(container, text='Tabela de Cargos & Faixa Salarial', bg='#ffffff', fg='#0f172a', font=('Segoe UI', 15, 'bold')).pack(anchor='w')
        self.cargo_tree = ttk.Treeview(container, columns=('Cargo', 'Salário Atual', 'Status'), show='headings')
        for col, width in [('Cargo', 320), ('Salário Atual', 200), ('Status', 160)]:
            self.cargo_tree.heading(col, text=col)
            self.cargo_tree.column(col, width=width, anchor='center')
        toolbar = tk.Frame(container, bg='#ffffff')
        toolbar.pack(fill='x', pady=(10, 0))
        self.create_print_button(toolbar, 'Relação de Cargos', self.cargo_tree).pack(side='right')
        self.cargo_tree.pack(fill='both', expand=True, pady=(12, 0))
        return page

    def build_dependente_page(self):
        page = ttk.Frame(self.notebook, padding=16)
        left = tk.Frame(page, bg='#ffffff', pady=14, padx=14, bd=1, relief='solid')
        left.pack(side='left', fill='y', padx=(0, 12), ipadx=8, ipady=8)
        tk.Label(left, text='Cadastrar Dependente', bg='#ffffff', fg='#0f172a', font=('Segoe UI', 14, 'bold')).pack(anchor='w', pady=(0, 12))
        self.dep_emp_var = tk.StringVar()
        self.dep_nome_var = tk.StringVar()
        self.dep_parentesco_var = tk.StringVar(value='Filho(a)')

        tk.Label(left, text='Colaborador', bg='#ffffff', fg='#475569', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(10, 4))
        self.dep_employee_cb = ttk.Combobox(left, textvariable=self.dep_emp_var, state='readonly', width=30)
        self.dep_employee_cb.pack(fill='x', pady=(0, 10))

        tk.Label(left, text='Nome', bg='#ffffff', fg='#475569', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(10, 4))
        tk.Entry(left, textvariable=self.dep_nome_var, width=30).pack(fill='x', pady=(0, 10))

        tk.Label(left, text='Parentesco', bg='#ffffff', fg='#475569', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(10, 4))
        ttk.Combobox(
            left,
            textvariable=self.dep_parentesco_var,
            values=['Filho(a)', 'Cônjuge', 'Pais', 'Enteado(a)', 'Outro'],
            state='readonly',
            width=30,
        ).pack(fill='x', pady=(0, 10))
        self.dep_save_btn = tk.Button(
            left,
            text='Salvar Dependente',
            bg='#14b8a6',
            fg='white',
            font=('Segoe UI', 10, 'bold'),
            command=self.cadastrar_dependente,
        )
        self.dep_save_btn.pack(fill='x', pady=(16, 0))
        self.dep_cancel_btn = tk.Button(
            left,
            text='Cancelar Edição',
            bg='#e2e8f0',
            fg='#0f172a',
            font=('Segoe UI', 10, 'bold'),
            command=self.cancelar_edicao_dependente,
            state='disabled',
        )
        self.dep_cancel_btn.pack(fill='x', pady=(8, 0))

        right = tk.Frame(page, bg='#ffffff', bd=1, relief='solid', padx=12, pady=12)
        right.pack(fill='both', expand=True)
        tk.Label(right, text='Dependentes por Colaborador', bg='#ffffff', fg='#0f172a', font=('Segoe UI', 14, 'bold')).pack(anchor='w')
        self.dep_tree = ttk.Treeview(right, columns=('ID', 'Colaborador', 'Nome', 'Parentesco'), show='headings')
        self.dep_tree.column('ID', width=0, stretch=False)
        self.dep_tree.heading('ID', text='')
        for col, width in [('Colaborador', 220), ('Nome', 220), ('Parentesco', 180)]:
            self.dep_tree.heading(col, text=col)
            self.dep_tree.column(col, width=width, anchor='center')
        self.dep_tree['displaycolumns'] = ('Colaborador', 'Nome', 'Parentesco')
        self.dep_tree.pack(fill='both', expand=True, pady=(12, 0))

        action = tk.Frame(right, bg='#ffffff')
        action.pack(fill='x', pady=(10, 0))
        self.create_print_button(action, 'Relação de Dependentes', self.dep_tree).pack(side='left')
        self.create_print_selected_button(action, 'Relação de Dependentes', self.dep_tree).pack(side='left', padx=(6, 0))
        tk.Button(
            action,
            text='Editar Selecionado',
            bg='#f59e0b',
            fg='white',
            font=('Segoe UI', 10, 'bold'),
            command=self.editar_dependente,
        ).pack(side='left')
        tk.Button(
            action,
            text='Excluir Selecionado',
            bg='#ef4444',
            fg='white',
            font=('Segoe UI', 10, 'bold'),
            command=self.remover_dependente,
        ).pack(side='right')
        return page

    def build_contracheque_page(self):
        page = ttk.Frame(self.notebook, padding=16)
        left = tk.Frame(page, bg='#ffffff', pady=14, padx=14, bd=1, relief='solid')
        left.pack(side='left', fill='y', padx=(0, 12), ipadx=8, ipady=8)
        tk.Label(left, text='Emissão de Contracheque', bg='#ffffff', fg='#0f172a', font=('Segoe UI', 14, 'bold')).pack(anchor='w', pady=(0, 12))

        self.cc_emp_var = tk.StringVar()
        self.cc_mes_var = tk.StringVar()
        self.cc_bruto_var = tk.StringVar()
        self.cc_desconto_var = tk.StringVar(value='0.00')
        self.cc_liquido_var = tk.StringVar(value='R$ 0,00')

        tk.Label(left, text='Colaborador', bg='#ffffff', fg='#475569', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(10, 4))
        self.cc_employee_cb = ttk.Combobox(left, textvariable=self.cc_emp_var, state='readonly', width=30)
        self.cc_employee_cb.pack(fill='x', pady=(0, 10))
        self.cc_employee_cb.bind('<<ComboboxSelected>>', self.on_select_employee_for_payroll)
        self.cc_desconto_var.trace_add('write', lambda *_: self.calcular_liquido_preview())

        tk.Label(left, text='Mês/Ano', bg='#ffffff', fg='#475569', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(10, 4))
        tk.Entry(left, textvariable=self.cc_mes_var, width=30).pack(fill='x', pady=(0, 10))
        tk.Label(left, text='Salário Bruto', bg='#ffffff', fg='#475569', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(10, 4))
        tk.Entry(left, textvariable=self.cc_bruto_var, width=30, state='readonly').pack(fill='x', pady=(0, 10))
        tk.Label(left, text='Descontos', bg='#ffffff', fg='#475569', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(10, 4))
        tk.Entry(left, textvariable=self.cc_desconto_var, width=30).pack(fill='x', pady=(0, 10))
        tk.Label(left, text='Líquido Previsto', bg='#ffffff', fg='#475569', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(10, 4))
        tk.Label(left, textvariable=self.cc_liquido_var, bg='#ecfdf5', fg='#065f46', font=('Segoe UI', 13, 'bold'), bd=1, relief='solid', padx=8, pady=8).pack(fill='x', pady=(0, 10))
        self.cc_save_btn = tk.Button(
            left,
            text='Gerar Holerite',
            bg='#10b981',
            fg='white',
            font=('Segoe UI', 10, 'bold'),
            command=self.gerar_contracheque,
        )
        self.cc_save_btn.pack(fill='x', pady=(8, 0))
        self.cc_cancel_btn = tk.Button(
            left,
            text='Cancelar Edição',
            bg='#e2e8f0',
            fg='#0f172a',
            font=('Segoe UI', 10, 'bold'),
            command=self.cancelar_edicao_contracheque,
            state='disabled',
        )
        self.cc_cancel_btn.pack(fill='x', pady=(8, 0))

        right = tk.Frame(page, bg='#ffffff', bd=1, relief='solid', padx=12, pady=12)
        right.pack(fill='both', expand=True)
        tk.Label(right, text='Histórico de Holerites', bg='#ffffff', fg='#0f172a', font=('Segoe UI', 14, 'bold')).pack(anchor='w')
        self.cc_tree = ttk.Treeview(right, columns=('ID', 'Colaborador', 'Mês', 'Bruto', 'Descontos', 'Líquido'), show='headings')
        self.cc_tree.column('ID', width=0, stretch=False)
        self.cc_tree.heading('ID', text='')
        for col, width in [('Colaborador', 200), ('Mês', 120), ('Bruto', 140), ('Descontos', 140), ('Líquido', 150)]:
            self.cc_tree.heading(col, text=col)
            self.cc_tree.column(col, width=width, anchor='center')
        self.cc_tree['displaycolumns'] = ('Colaborador', 'Mês', 'Bruto', 'Descontos', 'Líquido')
        self.cc_tree.pack(fill='both', expand=True, pady=(12, 0))

        action = tk.Frame(right, bg='#ffffff')
        action.pack(fill='x', pady=(10, 0))
        self.create_print_button(action, 'Relação de Contracheques', self.cc_tree).pack(side='left')
        self.create_print_selected_button(action, 'Relação de Contracheques', self.cc_tree).pack(side='left', padx=(6, 0))
        tk.Button(
            action,
            text='Editar Selecionado',
            bg='#f59e0b',
            fg='white',
            font=('Segoe UI', 10, 'bold'),
            command=self.editar_contracheque,
        ).pack(side='left')
        tk.Button(
            action,
            text='Excluir Selecionado',
            bg='#ef4444',
            fg='white',
            font=('Segoe UI', 10, 'bold'),
            command=self.remover_contracheque,
        ).pack(side='right')
        return page

    def build_ponto_page(self):
        page = ttk.Frame(self.notebook, padding=16)
        left = tk.Frame(page, bg='#ffffff', pady=14, padx=14, bd=1, relief='solid')
        left.pack(side='left', fill='y', padx=(0, 12), ipadx=8, ipady=8)
        tk.Label(left, text='Registrar Ponto', bg='#ffffff', fg='#0f172a', font=('Segoe UI', 14, 'bold')).pack(anchor='w', pady=(0, 12))
        self.ponto_emp_var = tk.StringVar()
        self.ponto_data_var = tk.StringVar(value=str(date.today()))
        self.ponto_entrada_var = tk.StringVar(value='08:00')
        self.ponto_saida_var = tk.StringVar(value='17:00')

        tk.Label(left, text='Colaborador', bg='#ffffff', fg='#475569', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(10, 4))
        self.ponto_employee_cb = ttk.Combobox(left, textvariable=self.ponto_emp_var, state='readonly', width=30)
        self.ponto_employee_cb.pack(fill='x', pady=(0, 10))

        tk.Label(left, text='Data', bg='#ffffff', fg='#475569', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(10, 4))
        tk.Entry(left, textvariable=self.ponto_data_var, width=30).pack(fill='x', pady=(0, 10))
        tk.Label(left, text='Entrada', bg='#ffffff', fg='#475569', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(10, 4))
        tk.Entry(left, textvariable=self.ponto_entrada_var, width=30).pack(fill='x', pady=(0, 10))
        tk.Label(left, text='Saída', bg='#ffffff', fg='#475569', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(10, 4))
        tk.Entry(left, textvariable=self.ponto_saida_var, width=30).pack(fill='x', pady=(0, 10))
        self.ponto_save_btn = tk.Button(
            left,
            text='Salvar Registro',
            bg='#2563eb',
            fg='white',
            font=('Segoe UI', 10, 'bold'),
            command=self.cadastrar_ponto,
        )
        self.ponto_save_btn.pack(fill='x', pady=(16, 0))
        self.ponto_cancel_btn = tk.Button(
            left,
            text='Cancelar Edição',
            bg='#e2e8f0',
            fg='#0f172a',
            font=('Segoe UI', 10, 'bold'),
            command=self.cancelar_edicao_ponto,
            state='disabled',
        )
        self.ponto_cancel_btn.pack(fill='x', pady=(8, 0))

        right = tk.Frame(page, bg='#ffffff', bd=1, relief='solid', padx=12, pady=12)
        right.pack(fill='both', expand=True)
        tk.Label(right, text='Registros Recentes', bg='#ffffff', fg='#0f172a', font=('Segoe UI', 14, 'bold')).pack(anchor='w')
        self.ponto_tree = ttk.Treeview(right, columns=('ID', 'Colaborador', 'Data', 'Entrada', 'Saída'), show='headings')
        self.ponto_tree.column('ID', width=0, stretch=False)
        self.ponto_tree.heading('ID', text='')
        for col, width in [('Colaborador', 220), ('Data', 150), ('Entrada', 120), ('Saída', 120)]:
            self.ponto_tree.heading(col, text=col)
            self.ponto_tree.column(col, width=width, anchor='center')
        self.ponto_tree['displaycolumns'] = ('Colaborador', 'Data', 'Entrada', 'Saída')
        self.ponto_tree.pack(fill='both', expand=True, pady=(12, 0))

        action = tk.Frame(right, bg='#ffffff')
        action.pack(fill='x', pady=(10, 0))
        self.create_print_button(action, 'Relação de Ponto', self.ponto_tree).pack(side='left')
        self.create_print_selected_button(action, 'Relação de Ponto', self.ponto_tree).pack(side='left', padx=(6, 0))
        tk.Button(
            action,
            text='Editar Selecionado',
            bg='#f59e0b',
            fg='white',
            font=('Segoe UI', 10, 'bold'),
            command=self.editar_ponto,
        ).pack(side='left')
        tk.Button(
            action,
            text='Excluir Selecionado',
            bg='#ef4444',
            fg='white',
            font=('Segoe UI', 10, 'bold'),
            command=self.remover_ponto,
        ).pack(side='right')
        return page

    def build_ferias_page(self):
        page = ttk.Frame(self.notebook, padding=16)
        left = tk.Frame(page, bg='#ffffff', pady=14, padx=14, bd=1, relief='solid')
        left.pack(side='left', fill='y', padx=(0, 12), ipadx=8, ipady=8)
        tk.Label(left, text='Solicitar Férias', bg='#ffffff', fg='#0f172a', font=('Segoe UI', 14, 'bold')).pack(anchor='w', pady=(0, 12))
        self.ferias_emp_var = tk.StringVar()
        self.ferias_inicio_var = tk.StringVar(value=str(date.today()))
        self.ferias_fim_var = tk.StringVar(value=str(date.today()))

        tk.Label(left, text='Colaborador', bg='#ffffff', fg='#475569', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(10, 4))
        self.ferias_employee_cb = ttk.Combobox(left, textvariable=self.ferias_emp_var, state='readonly', width=30)
        self.ferias_employee_cb.pack(fill='x', pady=(0, 10))

        tk.Label(left, text='Data Inicial', bg='#ffffff', fg='#475569', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(10, 4))
        tk.Entry(left, textvariable=self.ferias_inicio_var, width=30).pack(fill='x', pady=(0, 10))
        tk.Label(left, text='Data Final', bg='#ffffff', fg='#475569', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(10, 4))
        tk.Entry(left, textvariable=self.ferias_fim_var, width=30).pack(fill='x', pady=(0, 10))
        self.ferias_save_btn = tk.Button(
            left,
            text='Enviar Solicitação',
            bg='#f59e0b',
            fg='white',
            font=('Segoe UI', 10, 'bold'),
            command=self.cadastrar_ferias,
        )
        self.ferias_save_btn.pack(fill='x', pady=(16, 0))
        self.ferias_cancel_btn = tk.Button(
            left,
            text='Cancelar Edição',
            bg='#e2e8f0',
            fg='#0f172a',
            font=('Segoe UI', 10, 'bold'),
            command=self.cancelar_edicao_ferias,
            state='disabled',
        )
        self.ferias_cancel_btn.pack(fill='x', pady=(8, 0))

        right = tk.Frame(page, bg='#ffffff', bd=1, relief='solid', padx=12, pady=12)
        right.pack(fill='both', expand=True)
        tk.Label(right, text='Solicitações de Férias', bg='#ffffff', fg='#0f172a', font=('Segoe UI', 14, 'bold')).pack(anchor='w')
        self.ferias_tree = ttk.Treeview(right, columns=('ID', 'Colaborador', 'Início', 'Fim', 'Status'), show='headings')
        self.ferias_tree.column('ID', width=0, stretch=False)
        self.ferias_tree.heading('ID', text='')
        for col, width in [('Colaborador', 200), ('Início', 130), ('Fim', 130), ('Status', 140)]:
            self.ferias_tree.heading(col, text=col)
            self.ferias_tree.column(col, width=width, anchor='center')
        self.ferias_tree['displaycolumns'] = ('Colaborador', 'Início', 'Fim', 'Status')
        self.ferias_tree.pack(fill='both', expand=True, pady=(12, 0))

        action = tk.Frame(right, bg='#ffffff')
        action.pack(fill='x', pady=(10, 0))
        self.create_print_button(action, 'Relação de Férias', self.ferias_tree).pack(side='left')
        self.create_print_selected_button(action, 'Relação de Férias', self.ferias_tree).pack(side='left', padx=(6, 0))
        tk.Button(
            action,
            text='Marcar como Cumprido',
            bg='#16a34a',
            fg='white',
            font=('Segoe UI', 10, 'bold'),
            command=self.marcar_ferias_cumpridas,
        ).pack(side='left', padx=(6, 0))
        tk.Button(
            action,
            text='Editar Selecionado',
            bg='#f59e0b',
            fg='white',
            font=('Segoe UI', 10, 'bold'),
            command=self.editar_ferias,
        ).pack(side='left')
        tk.Button(
            action,
            text='Excluir Selecionado',
            bg='#ef4444',
            fg='white',
            font=('Segoe UI', 10, 'bold'),
            command=self.remover_ferias,
        ).pack(side='right')
        return page

    def build_treinamentos_page(self):
        page = ttk.Frame(self.notebook, padding=16)
        left = tk.Frame(page, bg='#ffffff', bd=1, relief='solid', padx=14, pady=14)
        left.pack(side='left', fill='y', padx=(0, 12))
        tk.Label(left, text='Cadastro de Treinamento', bg='#ffffff', fg='#0f172a', font=('Segoe UI', 14, 'bold')).pack(anchor='w', pady=(0, 8))

        self.treinamento_titulo_var = tk.StringVar()
        self.treinamento_categoria_var = tk.StringVar()
        self.treinamento_carga_var = tk.StringVar()
        self.treinamento_modalidade_var = tk.StringVar(value='EAD')
        for label, variable in (
            ('Nome do treinamento', self.treinamento_titulo_var),
            ('Categoria', self.treinamento_categoria_var),
            ('Carga horária (horas)', self.treinamento_carga_var),
        ):
            tk.Label(left, text=label, bg='#ffffff', fg='#475569', font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(8, 4))
            tk.Entry(left, textvariable=variable, width=32).pack(fill='x')

        tk.Label(left, text='Modalidade', bg='#ffffff', fg='#475569', font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(8, 4))
        ttk.Combobox(
            left,
            textvariable=self.treinamento_modalidade_var,
            values=('EAD', 'Online', 'Presencial', 'Híbrido'),
            state='readonly',
            width=30,
        ).pack(fill='x')
        self.treinamento_save_btn = tk.Button(
            left,
            text='Cadastrar Treinamento',
            bg='#4f46e5',
            fg='white',
            font=('Segoe UI', 10, 'bold'),
            command=self.salvar_treinamento,
        )
        self.treinamento_save_btn.pack(fill='x', pady=(12, 0))
        self.treinamento_cancel_btn = tk.Button(
            left,
            text='Cancelar Edição',
            bg='#e2e8f0',
            fg='#0f172a',
            font=('Segoe UI', 10, 'bold'),
            command=self.cancelar_edicao_treinamento,
            state='disabled',
        )
        self.treinamento_cancel_btn.pack(fill='x', pady=(6, 0))

        tk.Label(left, text='Inscrever colaborador', bg='#ffffff', fg='#0f172a', font=('Segoe UI', 12, 'bold')).pack(anchor='w', pady=(24, 8))
        self.treinamento_funcionario_var = tk.StringVar()
        self.treinamento_employee_cb = ttk.Combobox(
            left,
            textvariable=self.treinamento_funcionario_var,
            state='readonly',
            width=30,
        )
        self.treinamento_employee_cb.pack(fill='x')
        tk.Button(
            left,
            text='Inscrever no Treinamento Selecionado',
            bg='#0f766e',
            fg='white',
            font=('Segoe UI', 9, 'bold'),
            command=self.inscrever_funcionario_treinamento,
            wraplength=220,
        ).pack(fill='x', pady=(8, 0))

        right = tk.Frame(page, bg='#ffffff', bd=1, relief='solid', padx=12, pady=12)
        right.pack(fill='both', expand=True)
        tk.Label(right, text='Treinamentos Cadastrados', bg='#ffffff', fg='#0f172a', font=('Segoe UI', 14, 'bold')).pack(anchor='w')
        self.treinamento_tree = ttk.Treeview(
            right,
            columns=('ID', 'Treinamento', 'Categoria', 'Carga Horária', 'Modalidade', 'Inscritos'),
            show='headings',
            height=8,
        )
        self.treinamento_tree.column('ID', width=0, stretch=False)
        self.treinamento_tree.heading('ID', text='')
        for col, width in (
            ('Treinamento', 250),
            ('Categoria', 110),
            ('Carga Horária', 110),
            ('Modalidade', 110),
            ('Inscritos', 80),
        ):
            self.treinamento_tree.heading(col, text=col)
            self.treinamento_tree.column(col, width=width, anchor='center')
        self.treinamento_tree['displaycolumns'] = ('Treinamento', 'Categoria', 'Carga Horária', 'Modalidade', 'Inscritos')
        self.treinamento_tree.pack(fill='both', expand=True, pady=(8, 0))
        self.treinamento_tree.bind('<<TreeviewSelect>>', self.on_select_treinamento)

        actions = tk.Frame(right, bg='#ffffff')
        actions.pack(fill='x', pady=(8, 12))
        self.create_print_button(actions, 'Relação de Treinamentos', self.treinamento_tree).pack(side='left')
        self.create_print_selected_button(actions, 'Relação de Treinamentos', self.treinamento_tree).pack(side='left', padx=(6, 0))
        tk.Button(
            actions,
            text='Editar Selecionado',
            bg='#f59e0b',
            fg='white',
            font=('Segoe UI', 9, 'bold'),
            command=self.editar_treinamento,
        ).pack(side='left', padx=(6, 0))

        tk.Label(right, text='Colaboradores Inscritos', bg='#ffffff', fg='#0f172a', font=('Segoe UI', 12, 'bold')).pack(anchor='w')
        self.treinamento_inscritos_tree = ttk.Treeview(
            right,
            columns=('ID', 'Colaborador', 'Cargo', 'Setor'),
            show='headings',
            height=6,
        )
        self.treinamento_inscritos_tree.column('ID', width=0, stretch=False)
        self.treinamento_inscritos_tree.heading('ID', text='')
        for col, width in (('Colaborador', 240), ('Cargo', 200), ('Setor', 150)):
            self.treinamento_inscritos_tree.heading(col, text=col)
            self.treinamento_inscritos_tree.column(col, width=width, anchor='center')
        self.treinamento_inscritos_tree['displaycolumns'] = ('Colaborador', 'Cargo', 'Setor')
        self.treinamento_inscritos_tree.pack(fill='both', expand=True, pady=(8, 0))
        roster_actions = tk.Frame(right, bg='#ffffff')
        roster_actions.pack(fill='x', pady=(8, 0))
        self.create_print_button(roster_actions, 'Relação de Inscritos', self.treinamento_inscritos_tree).pack(side='left')
        tk.Button(
            roster_actions,
            text='Remover Colaborador do Treinamento',
            bg='#ef4444',
            fg='white',
            font=('Segoe UI', 9, 'bold'),
            command=self.remover_inscricao_treinamento,
        ).pack(side='right')
        return page

    def build_users_page(self):
        page = ttk.Frame(self.notebook, padding=16)
        form = tk.Frame(page, bg='white', bd=1, relief='solid', padx=16, pady=16)
        form.pack(side='left', fill='y', padx=(0, 12))
        tk.Label(
            form,
            text='Gerenciar Usuários',
            bg='white',
            fg='#0f172a',
            font=('Segoe UI', 14, 'bold'),
        ).pack(anchor='w', pady=(0, 8))

        self.user_username_var = tk.StringVar()
        self.user_password_var = tk.StringVar()
        self.user_role_var = tk.StringVar(value='Usuário')
        for label, variable, show in (
            ('Nome de usuário', self.user_username_var, None),
            ('Senha (mínimo de 8 caracteres)', self.user_password_var, '*'),
        ):
            tk.Label(form, text=label, bg='white', fg='#475569', font=('Segoe UI', 9, 'bold')).pack(
                anchor='w',
                pady=(8, 4),
            )
            tk.Entry(form, textvariable=variable, show=show, width=32).pack(fill='x')

        tk.Label(form, text='Perfil de acesso', bg='white', fg='#475569', font=('Segoe UI', 9, 'bold')).pack(
            anchor='w',
            pady=(8, 4),
        )
        ttk.Combobox(
            form,
            textvariable=self.user_role_var,
            values=('Usuário', 'Administrador'),
            state='readonly',
            width=30,
        ).pack(fill='x')
        self.user_save_btn = tk.Button(
            form,
            text='Cadastrar Usuário',
            bg='#2563eb',
            fg='white',
            font=('Segoe UI', 10, 'bold'),
            command=self.save_user,
        )
        self.user_save_btn.pack(fill='x', pady=(14, 0), ipady=4)
        self.user_cancel_btn = tk.Button(
            form,
            text='Cancelar Edição',
            bg='#e2e8f0',
            fg='#0f172a',
            font=('Segoe UI', 9, 'bold'),
            command=self.cancel_user_edit,
            state='disabled',
        )
        self.user_cancel_btn.pack(fill='x', pady=(6, 0), ipady=3)

        listing = tk.Frame(page, bg='white', bd=1, relief='solid', padx=12, pady=12)
        listing.pack(fill='both', expand=True)
        tk.Label(
            listing,
            text='Contas cadastradas',
            bg='white',
            fg='#0f172a',
            font=('Segoe UI', 14, 'bold'),
        ).pack(anchor='w')
        self.user_tree = ttk.Treeview(
            listing,
            columns=('ID', 'Usuário', 'Perfil'),
            show='headings',
        )
        self.user_tree.heading('ID', text='')
        self.user_tree.column('ID', width=0, stretch=False)
        self.user_tree.heading('Usuário', text='Usuário')
        self.user_tree.column('Usuário', width=240, anchor='w')
        self.user_tree.heading('Perfil', text='Perfil')
        self.user_tree.column('Perfil', width=180, anchor='center')
        self.user_tree.pack(fill='both', expand=True, pady=(8, 0))
        self.user_tree.bind('<<TreeviewSelect>>', self.select_user_for_edit)

        actions = tk.Frame(listing, bg='white')
        actions.pack(fill='x', pady=(8, 0))
        tk.Button(
            actions,
            text='Excluir Usuário Selecionado',
            bg='#ef4444',
            fg='white',
            font=('Segoe UI', 9, 'bold'),
            command=self.delete_user,
        ).pack(side='right')
        self.refresh_users()
        return page

    def refresh_users(self):
        if not hasattr(self, 'user_tree'):
            return
        with connect_db() as conn:
            rows = conn.execute('SELECT id, username, role FROM usuarios ORDER BY username').fetchall()
        self.user_tree.delete(*self.user_tree.get_children())
        for row in rows:
            self.user_tree.insert('', 'end', values=(row['id'], row['username'], row['role']))

    def select_user_for_edit(self, _event=None):
        selected = self.user_tree.selection()
        if not selected:
            return
        user_id = int(self.user_tree.item(selected[0], 'values')[0])
        with connect_db() as conn:
            user = conn.execute(
                'SELECT id, username, role FROM usuarios WHERE id = ?',
                (user_id,),
            ).fetchone()
        if user is None:
            self.refresh_users()
            return
        self.user_editing_id = user['id']
        self.user_username_var.set(user['username'])
        self.user_password_var.set('')
        self.user_role_var.set(user['role'])
        self.user_save_btn.config(text='Salvar Alterações')
        self.user_cancel_btn.config(state='normal')

    def cancel_user_edit(self):
        self.user_editing_id = None
        self.user_username_var.set('')
        self.user_password_var.set('')
        self.user_role_var.set('Usuário')
        self.user_save_btn.config(text='Cadastrar Usuário')
        self.user_cancel_btn.config(state='disabled')
        self.user_tree.selection_remove(self.user_tree.selection())

    def current_user_is_admin(self):
        with connect_db() as conn:
            row = conn.execute(
                'SELECT role FROM usuarios WHERE id = ?',
                (self.current_user['id'],),
            ).fetchone()
        return row is not None and row['role'] == 'Administrador'

    def save_user(self):
        if not self.current_user_is_admin():
            messagebox.showerror('Acesso negado', 'Somente administradores podem gerenciar usuários.')
            return
        username = self.user_username_var.get().strip()
        password = self.user_password_var.get()
        role = self.user_role_var.get()
        if not username or role not in ('Usuário', 'Administrador'):
            messagebox.showwarning('Dados incompletos', 'Informe o usuário e selecione um perfil válido.')
            return
        if self.user_editing_id is None and len(password) < 8:
            messagebox.showwarning('Senha muito curta', 'A senha deve ter pelo menos 8 caracteres.')
            return
        if password and len(password) < 8:
            messagebox.showwarning('Senha muito curta', 'A senha deve ter pelo menos 8 caracteres.')
            return
        if (
            self.user_editing_id == self.current_user['id']
            and role != self.current_user['role']
        ):
            messagebox.showwarning(
                'Perfil protegido',
                'Não é possível alterar o próprio perfil durante a sessão.',
            )
            return

        try:
            with connect_db() as conn:
                if self.user_editing_id is None:
                    salt, password_hash = hash_password(password)
                    conn.execute(
                        'INSERT INTO usuarios (username, password_salt, password_hash, role) '
                        'VALUES (?, ?, ?, ?)',
                        (username, salt, password_hash, role),
                    )
                else:
                    existing = conn.execute(
                        'SELECT username, role FROM usuarios WHERE id = ?',
                        (self.user_editing_id,),
                    ).fetchone()
                    if existing is None:
                        messagebox.showerror('Usuário não encontrado', 'Atualize a lista e tente novamente.')
                        self.refresh_users()
                        return
                    if existing['role'] == 'Administrador' and role != 'Administrador':
                        admin_count = conn.execute(
                            "SELECT COUNT(*) FROM usuarios WHERE role = 'Administrador'"
                        ).fetchone()[0]
                        if admin_count <= 1:
                            messagebox.showwarning(
                                'Ação não permitida',
                                'O sistema precisa manter pelo menos um administrador.',
                            )
                            return
                    conn.execute(
                        'UPDATE usuarios SET username = ?, role = ? WHERE id = ?',
                        (username, role, self.user_editing_id),
                    )
                    if password:
                        salt, password_hash = hash_password(password)
                        conn.execute(
                            'UPDATE usuarios SET password_salt = ?, password_hash = ? WHERE id = ?',
                            (salt, password_hash, self.user_editing_id),
                        )
                    if self.user_editing_id == self.current_user['id']:
                        self.current_user['username'] = username
        except sqlite3.IntegrityError:
            messagebox.showerror('Usuário já existe', 'Já existe uma conta com esse nome de usuário.')
            return

        self.cancel_user_edit()
        self.refresh_users()

    def delete_user(self):
        if not self.current_user_is_admin():
            messagebox.showerror('Acesso negado', 'Somente administradores podem gerenciar usuários.')
            return
        selected = self.user_tree.selection()
        if not selected:
            messagebox.showwarning('Nenhum usuário selecionado', 'Selecione uma conta para excluir.')
            return
        user_id, username, role = self.user_tree.item(selected[0], 'values')
        user_id = int(user_id)
        if user_id == self.current_user['id']:
            messagebox.showwarning('Ação não permitida', 'Não é possível excluir a conta em uso.')
            return
        if not messagebox.askyesno(
            'Confirmar exclusão',
            f'Deseja excluir a conta de usuário "{username}"?',
        ):
            return
        with connect_db() as conn:
            if role == 'Administrador':
                admin_count = conn.execute(
                    "SELECT COUNT(*) FROM usuarios WHERE role = 'Administrador'"
                ).fetchone()[0]
                if admin_count <= 1:
                    messagebox.showwarning(
                        'Ação não permitida',
                        'O sistema precisa manter pelo menos um administrador.',
                    )
                    return
            conn.execute('DELETE FROM usuarios WHERE id = ?', (user_id,))
        self.cancel_user_edit()
        self.refresh_users()

    def load_all_data(self):
        self.refresh_colaboradores()
        self.refresh_departamentos()
        self.refresh_cargos()
        self.refresh_dependentes()
        self.refresh_contracheques()
        self.refresh_pontos()
        self.refresh_ferias()
        self.refresh_employee_lists()
        self.refresh_treinamentos()
        self.update_kpis()

    def refresh_employee_lists(self):
        with connect_db() as conn:
            rows = conn.execute('SELECT id, nome FROM funcionarios ORDER BY nome').fetchall()
        nomes = [f'{r["id"]} - {r["nome"]}' for r in rows]
        self.dep_employee_cb['values'] = nomes
        self.cc_employee_cb['values'] = nomes
        self.ponto_employee_cb['values'] = nomes
        self.ferias_employee_cb['values'] = nomes
        self.treinamento_employee_cb['values'] = nomes
        if nomes:
            if not self.dep_emp_var.get():
                self.dep_emp_var.set(nomes[0])
            if not self.cc_emp_var.get():
                self.cc_emp_var.set(nomes[0])
            if not self.ponto_emp_var.get():
                self.ponto_emp_var.set(nomes[0])
            if not self.ferias_emp_var.get():
                self.ferias_emp_var.set(nomes[0])
            if not self.treinamento_funcionario_var.get():
                self.treinamento_funcionario_var.set(nomes[0])
        elif self.treinamento_funcionario_var.get():
            self.treinamento_funcionario_var.set('')

    def refresh_colaboradores(self):
        with connect_db() as conn:
            rows = conn.execute('SELECT * FROM funcionarios ORDER BY nome').fetchall()
        self.colab_tree.delete(*self.colab_tree.get_children())
        for row in rows:
            self.colab_tree.insert('', 'end', values=(row['id'], row['nome'], row['cargo'], row['setor'], f"R$ {row['salario']:.2f}"))
        self.colaborador_total.config(text=f'{len(rows)} Registros')

    def parse_funcionario_id(self, valor):
        if not valor:
            return None
        valor = valor.strip()
        if ' - ' in valor:
            valor = valor.split(' - ', 1)[0]
        try:
            return int(valor)
        except (TypeError, ValueError):
            return None

    def cancelar_edicao_colaborador(self):
        self.editing_colaborador_id = None
        for key in self.colab_vars:
            self.colab_vars[key].set('')
        self.colab_save_btn.config(text='Cadastrar Colaborador')
        self.colab_cancel_btn.config(state='disabled')

    def editar_colaborador(self):
        selected = self.colab_tree.selection()
        if not selected:
            messagebox.showwarning('Nenhuma linha selecionada', 'Selecione um colaborador para editar.')
            return
        colaborador_id = int(self.colab_tree.item(selected[0])['values'][0])
        with connect_db() as conn:
            row = conn.execute('SELECT * FROM funcionarios WHERE id = ?', (colaborador_id,)).fetchone()
        if row is None:
            return
        self.editing_colaborador_id = colaborador_id
        self.colab_vars['nome'].set(row['nome'])
        self.colab_vars['cargo'].set(row['cargo'])
        self.colab_vars['setor'].set(row['setor'])
        self.colab_vars['salario'].set(f"{row['salario']:.2f}")
        self.colab_save_btn.config(text='Salvar Alterações')
        self.colab_cancel_btn.config(state='normal')

    def refresh_departamentos(self):
        with connect_db() as conn:
            rows = conn.execute(
                'SELECT setor, COUNT(*) AS qtd, AVG(salario) AS media FROM funcionarios GROUP BY setor ORDER BY setor'
            ).fetchall()
        self.dept_tree.delete(*self.dept_tree.get_children())
        for row in rows:
            self.dept_tree.insert('', 'end', values=(row['setor'], row['qtd'], f"R$ {float(row['media'] or 0):.2f}"))

    def refresh_cargos(self):
        with connect_db() as conn:
            rows = conn.execute(
                'SELECT cargo, MAX(salario) AS salario, COUNT(*) AS qtd FROM funcionarios GROUP BY cargo ORDER BY cargo'
            ).fetchall()
        self.cargo_tree.delete(*self.cargo_tree.get_children())
        for row in rows:
            self.cargo_tree.insert('', 'end', values=(row['cargo'], f"R$ {float(row['salario'] or 0):.2f}", 'Ativo'))

    def refresh_dependentes(self):
        with connect_db() as conn:
            rows = conn.execute(
                'SELECT d.id, f.nome AS colaborador, d.nome, d.parentesco FROM dependentes d JOIN funcionarios f ON f.id = d.funcionario_id ORDER BY f.nome, d.nome'
            ).fetchall()
        self.dep_tree.delete(*self.dep_tree.get_children())
        for row in rows:
            self.dep_tree.insert('', 'end', values=(row['id'], row['colaborador'], row['nome'], row['parentesco']))

    def refresh_contracheques(self):
        with connect_db() as conn:
            rows = conn.execute(
                'SELECT c.id, f.nome AS colaborador, c.mes_ano, c.salario_bruto, c.descontos, c.salario_liquido FROM contracheques c JOIN funcionarios f ON f.id = c.funcionario_id ORDER BY c.id DESC'
            ).fetchall()
        self.cc_tree.delete(*self.cc_tree.get_children())
        for row in rows:
            self.cc_tree.insert(
                '',
                'end',
                values=(
                    row['id'],
                    row['colaborador'],
                    row['mes_ano'],
                    f"R$ {float(row['salario_bruto'] or 0):.2f}",
                    f"R$ {float(row['descontos'] or 0):.2f}",
                    f"R$ {float(row['salario_liquido'] or 0):.2f}",
                ),
            )

    def refresh_pontos(self):
        with connect_db() as conn:
            rows = conn.execute(
                'SELECT p.id, f.nome AS colaborador, p.data, p.entrada, p.saida FROM ponto p JOIN funcionarios f ON f.id = p.funcionario_id ORDER BY p.data DESC'
            ).fetchall()
        self.ponto_tree.delete(*self.ponto_tree.get_children())
        for row in rows:
            self.ponto_tree.insert('', 'end', values=(row['id'], row['colaborador'], row['data'], row['entrada'], row['saida']))

    def refresh_ferias(self):
        with connect_db() as conn:
            rows = conn.execute(
                'SELECT fr.id, f.nome AS colaborador, fr.inicio, fr.fim, fr.status FROM ferias fr JOIN funcionarios f ON f.id = fr.funcionario_id ORDER BY fr.inicio DESC'
            ).fetchall()
        self.ferias_tree.delete(*self.ferias_tree.get_children())
        for row in rows:
            self.ferias_tree.insert('', 'end', values=(row['id'], row['colaborador'], row['inicio'], row['fim'], row['status']))

    def refresh_treinamentos(self):
        selected_course_id = self.selected_treinamento_id
        with connect_db() as conn:
            rows = conn.execute(
                'SELECT t.id, t.titulo, t.categoria, t.carga_horaria, t.modalidade, COUNT(ti.id) AS inscritos '
                'FROM treinamentos t LEFT JOIN treinamento_inscricoes ti ON ti.treinamento_id = t.id '
                'GROUP BY t.id ORDER BY t.titulo'
            ).fetchall()
        self.treinamento_tree.delete(*self.treinamento_tree.get_children())
        for row in rows:
            self.treinamento_tree.insert(
                '',
                'end',
                values=(
                    row['id'],
                    row['titulo'],
                    row['categoria'],
                    row['carga_horaria'],
                    row['modalidade'],
                    row['inscritos'],
                ),
            )

        if selected_course_id is not None:
            for item_id in self.treinamento_tree.get_children():
                if int(self.treinamento_tree.item(item_id, 'values')[0]) == selected_course_id:
                    self.treinamento_tree.selection_set(item_id)
                    self.treinamento_tree.focus(item_id)
                    break
            else:
                self.selected_treinamento_id = None
        if self.selected_treinamento_id is None:
            self.treinamento_inscritos_tree.delete(*self.treinamento_inscritos_tree.get_children())

    def on_select_treinamento(self, event=None):
        selected = self.treinamento_tree.selection()
        if not selected:
            self.selected_treinamento_id = None
            self.treinamento_inscritos_tree.delete(*self.treinamento_inscritos_tree.get_children())
            return
        self.selected_treinamento_id = int(self.treinamento_tree.item(selected[0], 'values')[0])
        self.refresh_treinamento_inscritos()

    def refresh_treinamento_inscritos(self):
        self.treinamento_inscritos_tree.delete(*self.treinamento_inscritos_tree.get_children())
        if self.selected_treinamento_id is None:
            return
        with connect_db() as conn:
            rows = conn.execute(
                'SELECT ti.id, f.nome, f.cargo, f.setor FROM treinamento_inscricoes ti '
                'JOIN funcionarios f ON f.id = ti.funcionario_id '
                'WHERE ti.treinamento_id = ? ORDER BY f.nome',
                (self.selected_treinamento_id,),
            ).fetchall()
        for row in rows:
            self.treinamento_inscritos_tree.insert(
                '',
                'end',
                values=(row['id'], row['nome'], row['cargo'], row['setor']),
            )

    def cancelar_edicao_treinamento(self):
        self.treinamento_editing_id = None
        self.treinamento_titulo_var.set('')
        self.treinamento_categoria_var.set('')
        self.treinamento_carga_var.set('')
        self.treinamento_modalidade_var.set('EAD')
        self.treinamento_save_btn.config(text='Cadastrar Treinamento')
        self.treinamento_cancel_btn.config(state='disabled')

    def editar_treinamento(self):
        selected = self.treinamento_tree.selection()
        if not selected:
            messagebox.showwarning('Nenhuma linha selecionada', 'Selecione um treinamento para editar.')
            return
        training_id = int(self.treinamento_tree.item(selected[0], 'values')[0])
        with connect_db() as conn:
            row = conn.execute('SELECT * FROM treinamentos WHERE id = ?', (training_id,)).fetchone()
        if row is None:
            messagebox.showerror('Registro não encontrado', 'Não foi possível localizar este treinamento.')
            return
        self.treinamento_editing_id = training_id
        self.treinamento_titulo_var.set(row['titulo'])
        self.treinamento_categoria_var.set(row['categoria'])
        self.treinamento_carga_var.set(str(row['carga_horaria']))
        self.treinamento_modalidade_var.set(row['modalidade'])
        self.treinamento_save_btn.config(text='Salvar Alterações')
        self.treinamento_cancel_btn.config(state='normal')

    def salvar_treinamento(self):
        titulo = self.treinamento_titulo_var.get().strip()
        categoria = self.treinamento_categoria_var.get().strip()
        carga_texto = self.treinamento_carga_var.get().strip()
        modalidade = self.treinamento_modalidade_var.get().strip()
        if not titulo or not categoria or not carga_texto or not modalidade:
            messagebox.showwarning('Dados incompletos', 'Preencha todos os campos do treinamento.')
            return
        try:
            carga_horaria = int(carga_texto)
            if carga_horaria <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror('Carga horária inválida', 'Informe um número inteiro de horas maior que zero.')
            return

        try:
            with connect_db() as conn:
                if self.treinamento_editing_id is not None:
                    conn.execute(
                        'UPDATE treinamentos SET titulo = ?, categoria = ?, carga_horaria = ?, modalidade = ? WHERE id = ?',
                        (titulo, categoria, carga_horaria, modalidade, self.treinamento_editing_id),
                    )
                    self.selected_treinamento_id = self.treinamento_editing_id
                else:
                    cursor = conn.execute(
                        'INSERT INTO treinamentos (titulo, categoria, carga_horaria, modalidade) VALUES (?, ?, ?, ?)',
                        (titulo, categoria, carga_horaria, modalidade),
                    )
                    self.selected_treinamento_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            messagebox.showerror('Treinamento duplicado', 'Já existe um treinamento com esse nome.')
            return

        self.cancelar_edicao_treinamento()
        self.refresh_treinamentos()

    def inscrever_funcionario_treinamento(self):
        if self.selected_treinamento_id is None:
            messagebox.showwarning('Treinamento não selecionado', 'Selecione um treinamento para inscrever colaboradores.')
            return
        funcionario_id = self.parse_funcionario_id(self.treinamento_funcionario_var.get())
        if funcionario_id is None:
            messagebox.showwarning('Colaborador não selecionado', 'Selecione um colaborador para inscrever.')
            return
        try:
            with connect_db() as conn:
                conn.execute(
                    'INSERT INTO treinamento_inscricoes (treinamento_id, funcionario_id) VALUES (?, ?)',
                    (self.selected_treinamento_id, funcionario_id),
                )
        except sqlite3.IntegrityError:
            messagebox.showinfo('Inscrição existente', 'Este colaborador já está inscrito neste treinamento.')
            return
        self.refresh_treinamentos()
        self.refresh_treinamento_inscritos()

    def remover_inscricao_treinamento(self):
        if self.selected_treinamento_id is None:
            messagebox.showwarning('Treinamento não selecionado', 'Selecione o treinamento do qual deseja remover o colaborador.')
            return
        selected = self.treinamento_inscritos_tree.selection()
        if not selected:
            messagebox.showwarning('Nenhum colaborador selecionado', 'Selecione um colaborador inscrito para remover.')
            return

        inscricao_id = int(self.treinamento_inscritos_tree.item(selected[0], 'values')[0])
        colaborador = self.treinamento_inscritos_tree.item(selected[0], 'values')[1]
        if not messagebox.askyesno(
            'Confirmar remoção',
            f'Deseja remover {colaborador} deste treinamento? O cadastro do colaborador será mantido.',
        ):
            return

        with connect_db() as conn:
            cursor = conn.execute(
                'DELETE FROM treinamento_inscricoes WHERE id = ? AND treinamento_id = ?',
                (inscricao_id, self.selected_treinamento_id),
            )
        if cursor.rowcount == 0:
            messagebox.showerror('Inscrição não encontrada', 'Não foi possível encontrar essa inscrição neste treinamento.')
            return

        self.refresh_treinamentos()
        self.refresh_treinamento_inscritos()

    def update_kpis(self):
        with connect_db() as conn:
            total = conn.execute('SELECT COUNT(*) AS total FROM funcionarios').fetchone()['total']
            media = conn.execute('SELECT AVG(salario) AS media FROM funcionarios').fetchone()['media'] or 0
            total_deptos = conn.execute('SELECT COUNT(DISTINCT setor) AS total FROM funcionarios').fetchone()['total']
            ferias_pendentes = conn.execute('SELECT COUNT(*) AS total FROM ferias WHERE status = "Pendente"').fetchone()['total']
        self.kpis['kpi_total_colaboradores'].config(text=str(total))
        self.kpis['kpi_media_salarial'].config(text=f'R$ {float(media):.2f}')
        self.kpis['kpi_total_deptos'].config(text=str(total_deptos))
        self.kpis['kpi_ferias_pendentes'].config(text=str(ferias_pendentes))

    def cadastrar_colaborador(self):
        nome = self.colab_vars['nome'].get().strip()
        cargo = self.colab_vars['cargo'].get().strip()
        setor = self.colab_vars['setor'].get().strip()
        salario = self.colab_vars['salario'].get().strip()
        if not nome or not cargo or not setor or not salario:
            messagebox.showwarning('Dados incompletos', 'Preencha todos os campos do colaborador.')
            return
        try:
            valor = float(salario)
        except ValueError:
            messagebox.showerror('Valor inválido', 'O salário deve ser um número válido.')
            return

        with connect_db() as conn:
            if self.editing_colaborador_id is not None:
                conn.execute(
                    'UPDATE funcionarios SET nome = ?, cargo = ?, setor = ?, salario = ? WHERE id = ?',
                    (nome, cargo, setor, valor, self.editing_colaborador_id),
                )
            else:
                conn.execute(
                    'INSERT INTO funcionarios (nome, cargo, setor, salario) VALUES (?, ?, ?, ?)',
                    (nome, cargo, setor, valor),
                )

        for key in self.colab_vars:
            self.colab_vars[key].set('')
        self.editing_colaborador_id = None
        self.colab_save_btn.config(text='Cadastrar Colaborador')
        self.colab_cancel_btn.config(state='disabled')
        self.load_all_data()

    def remover_colaborador(self):
        selected = self.colab_tree.selection()
        if not selected:
            messagebox.showwarning('Nenhuma linha selecionada', 'Selecione um colaborador para remover.')
            return

        colaborador_id = self.colab_tree.item(selected[0])['values'][0]
        if messagebox.askyesno('Confirmação', f'Deseja excluir o colaborador #{colaborador_id}?'):
            with connect_db() as conn:
                conn.execute('DELETE FROM dependentes WHERE funcionario_id = ?', (colaborador_id,))
                conn.execute('DELETE FROM contracheques WHERE funcionario_id = ?', (colaborador_id,))
                conn.execute('DELETE FROM ponto WHERE funcionario_id = ?', (colaborador_id,))
                conn.execute('DELETE FROM ferias WHERE funcionario_id = ?', (colaborador_id,))
                conn.execute(
                    'DELETE FROM treinamento_inscricoes WHERE funcionario_id = ?',
                    (colaborador_id,),
                )
                conn.execute('DELETE FROM beneficios WHERE funcionario_id = ?', (colaborador_id,))
                conn.execute(
                    'DELETE FROM avaliacoes_desempenho WHERE funcionario_id = ?',
                    (colaborador_id,),
                )
                conn.execute('DELETE FROM funcionarios WHERE id = ?', (colaborador_id,))
            self.load_all_data()

    def cancelar_edicao_dependente(self):
        self.dep_editing_id = None
        self.dep_emp_var.set('')
        self.dep_nome_var.set('')
        self.dep_parentesco_var.set('Filho(a)')
        self.dep_save_btn.config(text='Salvar Dependente')
        self.dep_cancel_btn.config(state='disabled')

    def editar_dependente(self):
        selected = self.dep_tree.selection()
        if not selected:
            messagebox.showwarning('Nenhuma linha selecionada', 'Selecione um dependente para editar.')
            return
        dependente_id = int(self.dep_tree.item(selected[0])['values'][0])
        with connect_db() as conn:
            row = conn.execute(
                'SELECT d.id, d.funcionario_id, f.nome AS colaborador, d.nome, d.parentesco FROM dependentes d JOIN funcionarios f ON f.id = d.funcionario_id WHERE d.id = ?',
                (dependente_id,),
            ).fetchone()
        if row is None:
            return
        self.dep_editing_id = dependente_id
        self.dep_emp_var.set(f"{row['funcionario_id']} - {row['colaborador']}")
        self.dep_nome_var.set(row['nome'])
        self.dep_parentesco_var.set(row['parentesco'])
        self.dep_save_btn.config(text='Salvar Alterações')
        self.dep_cancel_btn.config(state='normal')

    def remover_dependente(self):
        selected = self.dep_tree.selection()
        if not selected:
            messagebox.showwarning('Nenhuma linha selecionada', 'Selecione um dependente para excluir.')
            return
        dependente_id = int(self.dep_tree.item(selected[0])['values'][0])
        if messagebox.askyesno('Confirmação', 'Deseja excluir este dependente?'):
            with connect_db() as conn:
                conn.execute('DELETE FROM dependentes WHERE id = ?', (dependente_id,))
            self.cancelar_edicao_dependente()
            self.load_all_data()

    def cadastrar_dependente(self):
        valor = self.dep_emp_var.get().strip()
        nome = self.dep_nome_var.get().strip()
        parentesco = self.dep_parentesco_var.get().strip()
        if not valor or not nome or not parentesco:
            messagebox.showwarning('Dados incompletos', 'Selecione um colaborador, informe o nome e o parentesco.')
            return

        funcionario_id = self.parse_funcionario_id(valor)
        if funcionario_id is None:
            messagebox.showerror('Colaborador inválido', 'Selecione um colaborador válido.')
            return
        with connect_db() as conn:
            if self.dep_editing_id is not None:
                conn.execute(
                    'UPDATE dependentes SET funcionario_id = ?, nome = ?, parentesco = ? WHERE id = ?',
                    (funcionario_id, nome, parentesco, self.dep_editing_id),
                )
            else:
                conn.execute(
                    'INSERT INTO dependentes (funcionario_id, nome, parentesco) VALUES (?, ?, ?)',
                    (funcionario_id, nome, parentesco),
                )
        self.cancelar_edicao_dependente()
        self.load_all_data()

    def on_select_employee_for_payroll(self, event):
        valor = self.cc_emp_var.get().strip()
        if not valor:
            return
        funcionario_id = int(valor.split(' - ')[0])
        with connect_db() as conn:
            row = conn.execute('SELECT salario FROM funcionarios WHERE id = ?', (funcionario_id,)).fetchone()
        if row is not None:
            self.cc_bruto_var.set(f"{float(row['salario']):.2f}")
            self.calcular_liquido_preview()

    def calcular_liquido_preview(self):
        try:
            bruto = float(self.cc_bruto_var.get() or 0)
            desconto = float(self.cc_desconto_var.get() or 0)
            self.cc_liquido_var.set(f'R$ {max(0.0, bruto - desconto):.2f}')
        except ValueError:
            self.cc_liquido_var.set('R$ 0,00')

    def cancelar_edicao_contracheque(self):
        self.cc_editing_id = None
        self.cc_emp_var.set('')
        self.cc_mes_var.set('')
        self.cc_bruto_var.set('')
        self.cc_desconto_var.set('0.00')
        self.cc_liquido_var.set('R$ 0,00')
        self.cc_save_btn.config(text='Gerar Holerite')
        self.cc_cancel_btn.config(state='disabled')

    def editar_contracheque(self):
        selected = self.cc_tree.selection()
        if not selected:
            messagebox.showwarning('Nenhuma linha selecionada', 'Selecione um holerite para editar.')
            return
        contracheque_id = int(self.cc_tree.item(selected[0])['values'][0])
        with connect_db() as conn:
            row = conn.execute(
                'SELECT c.id, c.funcionario_id, f.nome AS colaborador, c.mes_ano, c.salario_bruto, c.descontos, c.salario_liquido FROM contracheques c JOIN funcionarios f ON f.id = c.funcionario_id WHERE c.id = ?',
                (contracheque_id,),
            ).fetchone()
        if row is None:
            return
        self.cc_editing_id = contracheque_id
        self.cc_emp_var.set(f"{row['funcionario_id']} - {row['colaborador']}")
        self.cc_mes_var.set(row['mes_ano'])
        self.cc_bruto_var.set(f"{float(row['salario_bruto']):.2f}")
        self.cc_desconto_var.set(f"{float(row['descontos']):.2f}")
        self.cc_liquido_var.set(f"R$ {float(row['salario_liquido']):.2f}")
        self.cc_save_btn.config(text='Salvar Alterações')
        self.cc_cancel_btn.config(state='normal')

    def remover_contracheque(self):
        selected = self.cc_tree.selection()
        if not selected:
            messagebox.showwarning('Nenhuma linha selecionada', 'Selecione um holerite para excluir.')
            return
        contracheque_id = int(self.cc_tree.item(selected[0])['values'][0])
        if messagebox.askyesno('Confirmação', 'Deseja excluir este contracheque?'):
            with connect_db() as conn:
                conn.execute('DELETE FROM contracheques WHERE id = ?', (contracheque_id,))
            self.cancelar_edicao_contracheque()
            self.load_all_data()

    def gerar_contracheque(self):
        valor = self.cc_emp_var.get().strip()
        mes_ano = self.cc_mes_var.get().strip()
        if not valor or not mes_ano:
            messagebox.showwarning('Dados incompletos', 'Selecione um colaborador e informe o mês/ano.')
            return
        try:
            bruto = float(self.cc_bruto_var.get() or 0)
            descontos = float(self.cc_desconto_var.get() or 0)
        except ValueError:
            messagebox.showerror('Valor inválido', 'Informe valores numéricos válidos para bruto e descontos.')
            return

        liquido = max(0.0, bruto - descontos)
        funcionario_id = self.parse_funcionario_id(valor)
        if funcionario_id is None:
            messagebox.showerror('Colaborador inválido', 'Selecione um colaborador válido.')
            return
        with connect_db() as conn:
            if self.cc_editing_id is not None:
                conn.execute(
                    'UPDATE contracheques SET funcionario_id = ?, mes_ano = ?, salario_bruto = ?, descontos = ?, salario_liquido = ? WHERE id = ?',
                    (funcionario_id, mes_ano, bruto, descontos, liquido, self.cc_editing_id),
                )
            else:
                conn.execute(
                    'INSERT INTO contracheques (funcionario_id, mes_ano, salario_bruto, descontos, salario_liquido) VALUES (?, ?, ?, ?, ?)',
                    (funcionario_id, mes_ano, bruto, descontos, liquido),
                )
        self.cancelar_edicao_contracheque()
        self.load_all_data()

    def cancelar_edicao_ponto(self):
        self.ponto_editing_id = None
        self.ponto_emp_var.set('')
        self.ponto_data_var.set(str(date.today()))
        self.ponto_entrada_var.set('08:00')
        self.ponto_saida_var.set('17:00')
        self.ponto_save_btn.config(text='Salvar Registro')
        self.ponto_cancel_btn.config(state='disabled')

    def editar_ponto(self):
        selected = self.ponto_tree.selection()
        if not selected:
            messagebox.showwarning('Nenhuma linha selecionada', 'Selecione um registro de ponto para editar.')
            return
        ponto_id = int(self.ponto_tree.item(selected[0])['values'][0])
        with connect_db() as conn:
            row = conn.execute(
                'SELECT p.id, p.funcionario_id, f.nome AS colaborador, p.data, p.entrada, p.saida FROM ponto p JOIN funcionarios f ON f.id = p.funcionario_id WHERE p.id = ?',
                (ponto_id,),
            ).fetchone()
        if row is None:
            return
        self.ponto_editing_id = ponto_id
        self.ponto_emp_var.set(f"{row['funcionario_id']} - {row['colaborador']}")
        self.ponto_data_var.set(row['data'])
        self.ponto_entrada_var.set(row['entrada'])
        self.ponto_saida_var.set(row['saida'])
        self.ponto_save_btn.config(text='Salvar Alterações')
        self.ponto_cancel_btn.config(state='normal')

    def remover_ponto(self):
        selected = self.ponto_tree.selection()
        if not selected:
            messagebox.showwarning('Nenhuma linha selecionada', 'Selecione um registro de ponto para excluir.')
            return
        ponto_id = int(self.ponto_tree.item(selected[0])['values'][0])
        if messagebox.askyesno('Confirmação', 'Deseja excluir este registro de ponto?'):
            with connect_db() as conn:
                conn.execute('DELETE FROM ponto WHERE id = ?', (ponto_id,))
            self.cancelar_edicao_ponto()
            self.load_all_data()

    def cadastrar_ponto(self):
        valor = self.ponto_emp_var.get().strip()
        data = self.ponto_data_var.get().strip()
        entrada = self.ponto_entrada_var.get().strip()
        saida = self.ponto_saida_var.get().strip()
        if not valor or not data or not entrada or not saida:
            messagebox.showwarning('Dados incompletos', 'Preencha colaborador, data, entrada e saída.')
            return

        funcionario_id = self.parse_funcionario_id(valor)
        if funcionario_id is None:
            messagebox.showerror('Colaborador inválido', 'Selecione um colaborador válido.')
            return
        with connect_db() as conn:
            if self.ponto_editing_id is not None:
                conn.execute(
                    'UPDATE ponto SET funcionario_id = ?, data = ?, entrada = ?, saida = ? WHERE id = ?',
                    (funcionario_id, data, entrada, saida, self.ponto_editing_id),
                )
            else:
                conn.execute(
                    'INSERT INTO ponto (funcionario_id, data, entrada, saida) VALUES (?, ?, ?, ?)',
                    (funcionario_id, data, entrada, saida),
                )
        self.cancelar_edicao_ponto()
        self.load_all_data()

    def cancelar_edicao_ferias(self):
        self.ferias_editing_id = None
        self.ferias_emp_var.set('')
        self.ferias_inicio_var.set(str(date.today()))
        self.ferias_fim_var.set(str(date.today()))
        self.ferias_save_btn.config(text='Enviar Solicitação')
        self.ferias_cancel_btn.config(state='disabled')

    def editar_ferias(self):
        selected = self.ferias_tree.selection()
        if not selected:
            messagebox.showwarning('Nenhuma linha selecionada', 'Selecione uma solicitação de férias para editar.')
            return
        ferias_id = int(self.ferias_tree.item(selected[0])['values'][0])
        with connect_db() as conn:
            row = conn.execute(
                'SELECT fr.id, fr.funcionario_id, f.nome AS colaborador, fr.inicio, fr.fim, fr.status FROM ferias fr JOIN funcionarios f ON f.id = fr.funcionario_id WHERE fr.id = ?',
                (ferias_id,),
            ).fetchone()
        if row is None:
            return
        self.ferias_editing_id = ferias_id
        self.ferias_emp_var.set(f"{row['funcionario_id']} - {row['colaborador']}")
        self.ferias_inicio_var.set(row['inicio'])
        self.ferias_fim_var.set(row['fim'])
        self.ferias_save_btn.config(text='Salvar Alterações')
        self.ferias_cancel_btn.config(state='normal')

    def remover_ferias(self):
        selected = self.ferias_tree.selection()
        if not selected:
            messagebox.showwarning('Nenhuma linha selecionada', 'Selecione uma solicitação de férias para excluir.')
            return
        ferias_id = int(self.ferias_tree.item(selected[0])['values'][0])
        if messagebox.askyesno('Confirmação', 'Deseja excluir esta solicitação de férias?'):
            with connect_db() as conn:
                conn.execute('DELETE FROM ferias WHERE id = ?', (ferias_id,))
            self.cancelar_edicao_ferias()
            self.load_all_data()

    def marcar_ferias_cumpridas(self):
        selected = self.ferias_tree.selection()
        if not selected:
            messagebox.showwarning('Nenhuma linha selecionada', 'Selecione uma solicitação de férias.')
            return

        ferias_id = int(self.ferias_tree.item(selected[0])['values'][0])
        if not messagebox.askyesno(
            'Confirmar conclusão',
            'Deseja alterar o status desta solicitação de férias para Cumprido?',
        ):
            return

        with connect_db() as conn:
            cursor = conn.execute(
                "UPDATE ferias SET status = 'Cumprido' WHERE id = ? AND status = 'Pendente'",
                (ferias_id,),
            )
        if cursor.rowcount == 0:
            messagebox.showinfo(
                'Status não alterado',
                'A solicitação não foi encontrada ou já está marcada como cumprida.',
            )
            return

        self.load_all_data()

    def cadastrar_ferias(self):
        valor = self.ferias_emp_var.get().strip()
        inicio = self.ferias_inicio_var.get().strip()
        fim = self.ferias_fim_var.get().strip()
        if not valor or not inicio or not fim:
            messagebox.showwarning('Dados incompletos', 'Selecione o colaborador e informe as datas.')
            return

        funcionario_id = self.parse_funcionario_id(valor)
        if funcionario_id is None:
            messagebox.showerror('Colaborador inválido', 'Selecione um colaborador válido.')
            return
        with connect_db() as conn:
            if self.ferias_editing_id is not None:
                conn.execute(
                    'UPDATE ferias SET funcionario_id = ?, inicio = ?, fim = ? WHERE id = ?',
                    (funcionario_id, inicio, fim, self.ferias_editing_id),
                )
            else:
                conn.execute(
                    'INSERT INTO ferias (funcionario_id, inicio, fim, status) VALUES (?, ?, ?, ?)',
                    (funcionario_id, inicio, fim, 'Pendente'),
                )
        self.cancelar_edicao_ferias()
        self.load_all_data()


if __name__ == '__main__':
    try:
        from web_app import run
        run()
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        messagebox.showerror(
            'Erro ao iniciar',
            f'O servidor web não pôde ser iniciado:\n{exc}',
        )
