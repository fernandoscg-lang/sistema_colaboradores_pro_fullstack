import hmac
import os
import secrets
import sqlite3
import threading
import webbrowser
from functools import wraps
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, session
from werkzeug.exceptions import HTTPException

import main as legacy


APP_NAME = 'Sistema de Gestão Corporativo'
EMPLOYEE_FIELDS = ('nome', 'cargo', 'setor', 'salario')
MODULES = {
    'employees': {
        'title': 'Colaboradores',
        'table': 'funcionarios',
        'fields': (
            ('nome', 'Nome', 'text'),
            ('cargo', 'Cargo', 'text'),
            ('setor', 'Departamento / Setor', 'text'),
            ('salario', 'Salário bruto (R$)', 'number'),
        ),
        'columns': ('nome', 'cargo', 'setor', 'salario'),
        'select': 'SELECT id, nome, cargo, setor, salario FROM funcionarios ORDER BY nome',
    },
    'dependents': {
        'title': 'Dependentes',
        'table': 'dependentes',
        'fields': (
            ('funcionario_id', 'Colaborador', 'employee'),
            ('nome', 'Nome', 'text'),
            ('parentesco', 'Parentesco', 'relationship'),
        ),
        'columns': ('colaborador', 'nome', 'parentesco'),
        'select': (
            'SELECT d.id, d.funcionario_id, f.nome AS colaborador, d.nome, d.parentesco '
            'FROM dependentes d JOIN funcionarios f ON f.id = d.funcionario_id '
            'ORDER BY f.nome, d.nome'
        ),
    },
    'payslips': {
        'title': 'Contracheques',
        'table': 'contracheques',
        'fields': (
            ('funcionario_id', 'Colaborador', 'employee'),
            ('mes_ano', 'Mês/Ano', 'month'),
            ('salario_bruto', 'Salário bruto (R$)', 'number'),
            ('descontos', 'Descontos (R$)', 'number'),
        ),
        'columns': ('colaborador', 'mes_ano', 'salario_bruto', 'descontos', 'salario_liquido'),
        'select': (
            'SELECT c.id, c.funcionario_id, f.nome AS colaborador, c.mes_ano, '
            'f.cargo, f.setor, c.salario_bruto, c.descontos, c.salario_liquido '
            'FROM contracheques c JOIN funcionarios f ON f.id = c.funcionario_id '
            'ORDER BY c.id DESC'
        ),
    },
    'attendance': {
        'title': 'Ponto',
        'table': 'ponto',
        'fields': (
            ('funcionario_id', 'Colaborador', 'employee'),
            ('data', 'Data', 'date'),
            ('entrada', 'Entrada', 'time'),
            ('saida', 'Saída', 'time'),
        ),
        'columns': ('colaborador', 'data', 'entrada', 'saida'),
        'select': (
            'SELECT p.id, p.funcionario_id, f.nome AS colaborador, f.cargo, f.setor, '
            'p.data, p.entrada, p.saida '
            'FROM ponto p JOIN funcionarios f ON f.id = p.funcionario_id ORDER BY p.data DESC'
        ),
    },
    'vacations': {
        'title': 'Férias',
        'table': 'ferias',
        'fields': (
            ('funcionario_id', 'Colaborador', 'employee'),
            ('inicio', 'Data inicial', 'date'),
            ('fim', 'Data final', 'date'),
        ),
        'columns': ('colaborador', 'inicio', 'fim', 'status'),
        'select': (
            'SELECT fr.id, fr.funcionario_id, f.nome AS colaborador, f.cargo, f.setor, '
            'fr.inicio, fr.fim, fr.status '
            'FROM ferias fr JOIN funcionarios f ON f.id = fr.funcionario_id '
            'ORDER BY fr.inicio DESC'
        ),
    },
    'trainings': {
        'title': 'Treinamentos',
        'table': 'treinamentos',
        'fields': (
            ('titulo', 'Nome do treinamento', 'text'),
            ('categoria', 'Categoria', 'text'),
            ('carga_horaria', 'Carga horária (horas)', 'positive_integer'),
            ('modalidade', 'Modalidade', 'modality'),
        ),
        'columns': ('titulo', 'categoria', 'carga_horaria', 'modalidade', 'inscritos'),
        'select': (
            'SELECT t.id, t.titulo, t.categoria, t.carga_horaria, t.modalidade, '
            'COUNT(ti.id) AS inscritos FROM treinamentos t '
            'LEFT JOIN treinamento_inscricoes ti ON ti.treinamento_id = t.id '
            'GROUP BY t.id ORDER BY t.titulo'
        ),
    },
}
DISPLAY_NAMES = {
    'nome': 'Nome',
    'cargo': 'Cargo',
    'setor': 'Setor',
    'salario': 'Salário',
    'colaborador': 'Colaborador',
    'parentesco': 'Parentesco',
    'mes_ano': 'Mês/Ano',
    'salario_bruto': 'Salário bruto',
    'descontos': 'Descontos',
    'salario_liquido': 'Salário líquido',
    'data': 'Data',
    'entrada': 'Entrada',
    'saida': 'Saída',
    'inicio': 'Início',
    'fim': 'Fim',
    'status': 'Status',
    'titulo': 'Treinamento',
    'categoria': 'Categoria',
    'carga_horaria': 'Carga horária',
    'modalidade': 'Modalidade',
    'inscritos': 'Inscritos',
    'funcionario_id': 'Colaborador',
    'username': 'Usuário',
    'role': 'Perfil',
}
RELATIONSHIPS = ('Filho(a)', 'Cônjuge', 'Pais', 'Enteado(a)', 'Outro')
MODALITIES = ('EAD', 'Online', 'Presencial', 'Híbrido')


def create_app(test_config=None):
    app = Flask(__name__)
    configured_secret = os.environ.get('SISTEMA_GESTAO_SECRET')
    if not configured_secret:
        secret_path = legacy.DB_DIR / '.web_session_secret'
        try:
            if secret_path.exists():
                configured_secret = secret_path.read_text(encoding='ascii').strip()
            else:
                configured_secret = secrets.token_hex(32)
                secret_path.write_text(configured_secret, encoding='ascii')
        except OSError as exc:
            raise RuntimeError(f'Não foi possível preparar a chave de sessão: {exc}') from exc
    app.config.update(
        SECRET_KEY=configured_secret,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Strict',
        PERMANENT_SESSION_LIFETIME=8 * 60 * 60,
        JSON_AS_ASCII=False,
    )
    if test_config:
        app.config.update(test_config)
    if not app.config.get('TESTING'):
        _configure_database()

    @app.get('/')
    def index():
        return render_template('index.html', app_name=APP_NAME)

    @app.get('/api/session')
    def get_session():
        with legacy.connect_db() as conn:
            needs_setup = conn.execute('SELECT COUNT(*) FROM usuarios').fetchone()[0] == 0
        token = session.setdefault('csrf_token', secrets.token_urlsafe(32))
        return jsonify({
            'needs_setup': needs_setup,
            'user': session.get('user'),
            'csrf_token': token,
        })

    @app.post('/api/auth/setup')
    def setup_first_admin():
        require_csrf()
        payload = request.get_json(silent=True) or {}
        username = str(payload.get('username', '')).strip()
        password = str(payload.get('password', ''))
        confirmation = str(payload.get('confirmation', ''))
        if not username or not password:
            return api_error('Informe usuário e senha.', 400)
        if len(password) < 8:
            return api_error('A senha deve ter pelo menos 8 caracteres.', 400)
        if password != confirmation:
            return api_error('As senhas informadas não coincidem.', 400)

        salt, password_hash = legacy.hash_password(password)
        try:
            with legacy.connect_db() as conn:
                conn.execute('BEGIN IMMEDIATE')
                if conn.execute('SELECT COUNT(*) FROM usuarios').fetchone()[0]:
                    return api_error('A configuração inicial já foi concluída.', 409)
                cursor = conn.execute(
                    'INSERT INTO usuarios (username, password_salt, password_hash, role) '
                    'VALUES (?, ?, ?, ?)',
                    (username, salt, password_hash, 'Administrador'),
                )
                user = {'id': cursor.lastrowid, 'username': username, 'role': 'Administrador'}
        except sqlite3.IntegrityError:
            return api_error('Esse nome de usuário já está em uso.', 409)
        session.clear()
        session['user'] = user
        session['csrf_token'] = secrets.token_urlsafe(32)
        session.permanent = True
        return jsonify({'user': user}), 201

    @app.post('/api/auth/login')
    def login():
        require_csrf()
        payload = request.get_json(silent=True) or {}
        username = str(payload.get('username', '')).strip()
        password = str(payload.get('password', ''))
        user = legacy.authenticate_user(username, password)
        if user is None:
            return api_error('Usuário ou senha incorretos.', 401)
        session.clear()
        session['user'] = user
        session['csrf_token'] = secrets.token_urlsafe(32)
        session.permanent = True
        return jsonify({'user': user})

    @app.post('/api/auth/logout')
    @authenticated
    def logout():
        require_csrf()
        session.clear()
        return jsonify({'ok': True})

    @app.get('/api/dashboard')
    @authenticated
    def dashboard():
        with legacy.connect_db() as conn:
            total = conn.execute('SELECT COUNT(*) FROM funcionarios').fetchone()[0]
            avg_salary = conn.execute('SELECT AVG(salario) FROM funcionarios').fetchone()[0] or 0
            departments = conn.execute(
                'SELECT COUNT(DISTINCT setor) FROM funcionarios'
            ).fetchone()[0]
            pending_vacations = conn.execute(
                "SELECT COUNT(*) FROM ferias WHERE status = 'Pendente'"
            ).fetchone()[0]
        settings = _load_settings()
        return jsonify({
            'kpis': {
                'employees': total,
                'average_salary': float(avg_salary),
                'departments': departments,
                'pending_vacations': pending_vacations,
            },
            'settings': {
                'theme': settings['theme'],
                'database_directory': settings['database_directory'],
                'database_path': str(legacy.database_path_for_settings(settings)),
                'default_database_directory': str(legacy.DB_DIR),
            },
            'user': session['user'],
            'modules': [
                {'key': key, 'title': value['title']}
                for key, value in MODULES.items()
            ] + [
                {'key': 'departments', 'title': 'Departamentos'},
                {'key': 'positions', 'title': 'Cargos'},
            ] + (
                [{'key': 'users', 'title': 'Usuários'},
                 {'key': 'settings', 'title': 'Configurações'}]
                if session['user']['role'] == 'Administrador'
                else [{'key': 'settings', 'title': 'Configurações'}]
            ),
        })

    @app.get('/api/modules/<module>')
    @authenticated
    def list_module(module):
        if module in MODULES:
            with legacy.connect_db() as conn:
                rows = conn.execute(MODULES[module]['select']).fetchall()
                result = [dict(row) for row in rows]
                if module == 'trainings':
                    for row in result:
                        row['enrolled_employees'] = _training_roster(conn, row['id'])
            return jsonify({
                'key': module,
                'title': MODULES[module]['title'],
                'fields': [
                    {'key': key, 'label': label, 'type': kind}
                    for key, label, kind in MODULES[module]['fields']
                ],
                'columns': [
                    {'key': key, 'label': DISPLAY_NAMES[key]}
                    for key in MODULES[module]['columns']
                ],
                'rows': result,
                'employees': _employees(),
                'relationships': RELATIONSHIPS,
                'modalities': MODALITIES,
            })
        if module == 'departments':
            with legacy.connect_db() as conn:
                rows = conn.execute(
                    'SELECT setor, COUNT(*) AS colaboradores, AVG(salario) AS media_salarial '
                    'FROM funcionarios GROUP BY setor ORDER BY setor'
                ).fetchall()
            return jsonify({
                'key': module,
                'title': 'Departamentos',
                'fields': [],
                'columns': [
                    {'key': 'setor', 'label': 'Departamento'},
                    {'key': 'colaboradores', 'label': 'Colaboradores'},
                    {'key': 'media_salarial', 'label': 'Média salarial'},
                ],
                'rows': [dict(row) for row in rows],
            })
        if module == 'positions':
            with legacy.connect_db() as conn:
                rows = conn.execute(
                    "SELECT cargo, MAX(salario) AS salario_atual, COUNT(*) AS quantidade "
                    "FROM funcionarios GROUP BY cargo ORDER BY cargo"
                ).fetchall()
            return jsonify({
                'key': module,
                'title': 'Cargos',
                'fields': [],
                'columns': [
                    {'key': 'cargo', 'label': 'Cargo'},
                    {'key': 'salario_atual', 'label': 'Salário atual'},
                    {'key': 'status', 'label': 'Status'},
                ],
                'rows': [
                    {**dict(row), 'status': 'Ativo'} for row in rows
                ],
            })
        if module == 'users':
            _require_admin()
            with legacy.connect_db() as conn:
                rows = conn.execute(
                    'SELECT id, username, role, created_at FROM usuarios ORDER BY username'
                ).fetchall()
            return jsonify({
                'key': module,
                'title': 'Usuários',
                'fields': [
                    {'key': 'username', 'label': 'Nome de usuário', 'type': 'text'},
                    {'key': 'password', 'label': 'Senha (mínimo de 8 caracteres)', 'type': 'password'},
                    {'key': 'role', 'label': 'Perfil de acesso', 'type': 'role'},
                ],
                'columns': [
                    {'key': 'username', 'label': 'Usuário'},
                    {'key': 'role', 'label': 'Perfil'},
                    {'key': 'created_at', 'label': 'Criado em'},
                ],
                'rows': [dict(row) for row in rows],
            })
        abort(404)

    @app.post('/api/modules/<module>')
    @authenticated
    def create_module_record(module):
        require_csrf()
        payload = request.get_json(silent=True) or {}
        if module == 'users':
            _require_admin()
            username = str(payload.get('username', '')).strip()
            password = str(payload.get('password', ''))
            role = payload.get('role')
            if not username or len(password) < 8 or role not in ('Administrador', 'Usuário'):
                return api_error('Informe usuário, senha com pelo menos 8 caracteres e perfil válido.', 400)
            salt, password_hash = legacy.hash_password(password)
            try:
                with legacy.connect_db() as conn:
                    conn.execute(
                        'INSERT INTO usuarios (username, password_salt, password_hash, role) '
                        'VALUES (?, ?, ?, ?)',
                        (username, salt, password_hash, role),
                    )
            except sqlite3.IntegrityError:
                return api_error('Esse nome de usuário já está em uso.', 409)
            return jsonify({'ok': True}), 201
        if module not in MODULES:
            abort(404)
        data, error = _validate_payload(module, payload)
        if error:
            return api_error(error, 400)
        table = MODULES[module]['table']
        fields = [field[0] for field in MODULES[module]['fields']]
        if module == 'payslips':
            data['salario_liquido'] = round(data['salario_bruto'] - data['descontos'], 2)
            fields.append('salario_liquido')
        placeholders = ', '.join('?' for _ in fields)
        names = ', '.join(fields)
        try:
            with legacy.connect_db() as conn:
                cursor = conn.execute(
                    f'INSERT INTO {table} ({names}) VALUES ({placeholders})',
                    tuple(data[field] for field in fields),
                )
        except sqlite3.IntegrityError as exc:
            return api_error(_integrity_error(module, exc), 409)
        return jsonify({'id': cursor.lastrowid}), 201

    @app.patch('/api/modules/<module>/<int:record_id>')
    @authenticated
    def update_module_record(module, record_id):
        require_csrf()
        payload = request.get_json(silent=True) or {}
        if module == 'users':
            _require_admin()
            username = str(payload.get('username', '')).strip()
            role = payload.get('role')
            password = str(payload.get('password', ''))
            if not username or role not in ('Administrador', 'Usuário'):
                return api_error('Informe usuário e perfil válido.', 400)
            if record_id == session['user']['id'] and role != 'Administrador':
                return api_error('Não é possível remover seu próprio perfil de administrador.', 400)
            try:
                with legacy.connect_db() as conn:
                    if password:
                        if len(password) < 8:
                            return api_error('A senha deve ter pelo menos 8 caracteres.', 400)
                        salt, password_hash = legacy.hash_password(password)
                        cursor = conn.execute(
                            'UPDATE usuarios SET username = ?, role = ?, password_salt = ?, '
                            'password_hash = ? WHERE id = ?',
                            (username, role, salt, password_hash, record_id),
                        )
                    else:
                        cursor = conn.execute(
                            'UPDATE usuarios SET username = ?, role = ? WHERE id = ?',
                            (username, role, record_id),
                        )
            except sqlite3.IntegrityError:
                return api_error('Esse nome de usuário já está em uso.', 409)
            if cursor.rowcount == 0:
                abort(404)
            if record_id == session['user']['id']:
                session['user']['username'] = username
                session['user']['role'] = role
            return jsonify({'ok': True})
        if module not in MODULES:
            abort(404)
        data, error = _validate_payload(module, payload)
        if error:
            return api_error(error, 400)
        fields = [field[0] for field in MODULES[module]['fields']]
        if module == 'payslips':
            data['salario_liquido'] = round(data['salario_bruto'] - data['descontos'], 2)
            fields.append('salario_liquido')
        assignments = ', '.join(f'{field} = ?' for field in fields)
        try:
            with legacy.connect_db() as conn:
                cursor = conn.execute(
                    f'UPDATE {MODULES[module]["table"]} SET {assignments} WHERE id = ?',
                    (*[data[field] for field in fields], record_id),
                )
        except sqlite3.IntegrityError as exc:
            return api_error(_integrity_error(module, exc), 409)
        if cursor.rowcount == 0:
            abort(404)
        return jsonify({'ok': True})

    @app.delete('/api/modules/<module>/<int:record_id>')
    @authenticated
    def delete_module_record(module, record_id):
        require_csrf()
        if module == 'users':
            _require_admin()
            if record_id == session['user']['id']:
                return api_error('Não é possível excluir o usuário conectado.', 400)
            with legacy.connect_db() as conn:
                admin_count = conn.execute(
                    "SELECT COUNT(*) FROM usuarios WHERE role = 'Administrador'"
                ).fetchone()[0]
                target = conn.execute(
                    'SELECT role FROM usuarios WHERE id = ?', (record_id,)
                ).fetchone()
                if target is None:
                    abort(404)
                if target['role'] == 'Administrador' and admin_count <= 1:
                    return api_error('O sistema precisa manter pelo menos um administrador.', 400)
                conn.execute('DELETE FROM usuarios WHERE id = ?', (record_id,))
            return jsonify({'ok': True})
        if module not in MODULES:
            abort(404)
        table = MODULES[module]['table']
        with legacy.connect_db() as conn:
            if module == 'employees':
                conn.execute('DELETE FROM treinamento_inscricoes WHERE funcionario_id = ?', (record_id,))
                for related_table in ('dependentes', 'contracheques', 'ponto', 'ferias'):
                    conn.execute(
                        f'DELETE FROM {related_table} WHERE funcionario_id = ?',
                        (record_id,),
                    )
            elif module == 'trainings':
                conn.execute(
                    'DELETE FROM treinamento_inscricoes WHERE treinamento_id = ?', (record_id,)
                )
            cursor = conn.execute(f'DELETE FROM {table} WHERE id = ?', (record_id,))
            if cursor.rowcount == 0:
                abort(404)
        return jsonify({'ok': True})

    @app.post('/api/vacations/<int:vacation_id>/complete')
    @authenticated
    def complete_vacation(vacation_id):
        require_csrf()
        with legacy.connect_db() as conn:
            cursor = conn.execute(
                "UPDATE ferias SET status = 'Cumprido' WHERE id = ? AND status = 'Pendente'",
                (vacation_id,),
            )
        if cursor.rowcount == 0:
            return api_error('Solicitação inexistente ou já cumprida.', 404)
        return jsonify({'ok': True})

    @app.get('/api/trainings/<int:training_id>/enrollments')
    @authenticated
    def get_enrollments(training_id):
        with legacy.connect_db() as conn:
            if not conn.execute(
                'SELECT 1 FROM treinamentos WHERE id = ?', (training_id,)
            ).fetchone():
                abort(404)
            return jsonify(_training_roster(conn, training_id))

    @app.post('/api/trainings/<int:training_id>/enrollments')
    @authenticated
    def add_enrollment(training_id):
        require_csrf()
        payload = request.get_json(silent=True) or {}
        try:
            employee_id = int(payload.get('funcionario_id'))
        except (TypeError, ValueError):
            return api_error('Selecione um colaborador válido.', 400)
        try:
            with legacy.connect_db() as conn:
                if not conn.execute(
                    'SELECT 1 FROM treinamentos WHERE id = ?', (training_id,)
                ).fetchone():
                    abort(404)
                if not conn.execute(
                    'SELECT 1 FROM funcionarios WHERE id = ?', (employee_id,)
                ).fetchone():
                    return api_error('O colaborador selecionado não existe.', 404)
                conn.execute(
                    'INSERT INTO treinamento_inscricoes (treinamento_id, funcionario_id) '
                    'VALUES (?, ?)',
                    (training_id, employee_id),
                )
        except sqlite3.IntegrityError as exc:
            if 'UNIQUE' in str(exc).upper():
                return api_error('Este colaborador já está inscrito neste treinamento.', 409)
            return api_error('Treinamento ou colaborador inexistente.', 404)
        return jsonify({'ok': True}), 201

    @app.delete('/api/trainings/<int:training_id>/enrollments/<int:enrollment_id>')
    @authenticated
    def remove_enrollment(training_id, enrollment_id):
        require_csrf()
        with legacy.connect_db() as conn:
            cursor = conn.execute(
                'DELETE FROM treinamento_inscricoes WHERE id = ? AND treinamento_id = ?',
                (enrollment_id, training_id),
            )
        if cursor.rowcount == 0:
            abort(404)
        return jsonify({'ok': True})

    @app.patch('/api/settings')
    @authenticated
    def update_settings():
        require_csrf()
        payload = request.get_json(silent=True) or {}
        settings = _load_settings()
        theme = payload.get('theme', settings['theme'])
        if theme not in ('light', 'dark'):
            return api_error('Tema inválido.', 400)
        settings['theme'] = theme
        if 'database_directory' in payload:
            _require_admin()
            directory = payload['database_directory']
            if directory in (None, ''):
                settings['database_directory'] = None
            elif not isinstance(directory, str) or not Path(directory).expanduser().is_dir():
                return api_error('Selecione uma pasta existente para o banco de dados.', 400)
            else:
                settings['database_directory'] = str(
                    Path(directory).expanduser().resolve()
                )
        try:
            legacy.save_app_settings(settings)
        except OSError as exc:
            return api_error(f'Não foi possível salvar as configurações: {exc}', 500)
        return jsonify({
            'theme': settings['theme'],
            'database_directory': settings['database_directory'],
            'database_path': str(legacy.database_path_for_settings(settings)),
            'default_database_directory': str(legacy.DB_DIR),
        })

    @app.before_request
    def enforce_csrf_for_mutations():
        if request.method in ('POST', 'PATCH', 'DELETE') and request.path.startswith('/api/'):
            if request.path not in ('/api/auth/setup', '/api/auth/login'):
                require_csrf()

    @app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Registro ou recurso não encontrado.'}), 404
        return 'Página não encontrada.', 404

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if request.path.startswith('/api/'):
            return jsonify({'error': error.description}), error.code
        return error

    @app.errorhandler(500)
    def internal_error(_error):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Erro interno ao processar a solicitação.'}), 500
        return 'Erro interno.', 500

    return app


def authenticated(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user'):
            return api_error('Faça login para continuar.', 401)
        return view(*args, **kwargs)
    return wrapped


def require_csrf():
    expected = session.get('csrf_token')
    supplied = request.headers.get('X-CSRF-Token')
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        abort(400, description='Token de segurança inválido. Atualize a página e tente novamente.')


def _require_admin():
    if session.get('user', {}).get('role') != 'Administrador':
        abort(403, description='Somente administradores podem executar esta ação.')


def api_error(message, status):
    return jsonify({'error': message}), status


def _load_settings():
    settings = legacy.load_app_settings()
    legacy.APP_SETTINGS = settings
    return settings


def _configure_database():
    settings = _load_settings()
    database_path = legacy.database_path_for_settings(settings)
    if settings['database_directory'] and not database_path.parent.is_dir():
        raise ValueError(f'A pasta configurada para o banco não existe: {database_path.parent}')
    database_path.parent.mkdir(parents=True, exist_ok=True)
    legacy.DB_PATH = database_path
    legacy.init_db()
    legacy.ensure_seed_data()
    legacy.ensure_training_seed_data()


def _employees():
    with legacy.connect_db() as conn:
        rows = conn.execute('SELECT id, nome FROM funcionarios ORDER BY nome').fetchall()
    return [dict(row) for row in rows]


def _training_roster(conn, training_id):
    rows = conn.execute(
        'SELECT ti.id, f.id AS funcionario_id, f.nome AS colaborador, f.cargo, f.setor '
        'FROM treinamento_inscricoes ti JOIN funcionarios f ON f.id = ti.funcionario_id '
        'WHERE ti.treinamento_id = ? ORDER BY f.nome',
        (training_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _validate_payload(module, payload):
    data = {}
    for key, label, kind in MODULES[module]['fields']:
        value = payload.get(key)
        if kind in ('text', 'relationship', 'modality', 'date', 'month', 'time'):
            value = str(value or '').strip()
            if not value:
                return None, f'Preencha o campo {label.lower()}.'
            if kind == 'relationship' and value not in RELATIONSHIPS:
                return None, 'Selecione um parentesco válido.'
            if kind == 'modality' and value not in MODALITIES:
                return None, 'Selecione uma modalidade válida.'
            if kind == 'date':
                try:
                    from datetime import date
                    date.fromisoformat(value)
                except ValueError:
                    return None, f'Informe uma data válida para {label.lower()}.'
            if kind == 'month' and (
                len(value) != 7 or value[2] != '/' or not value[:2].isdigit()
                or not value[3:].isdigit() or not 1 <= int(value[:2]) <= 12
            ):
                return None, 'Informe o mês e o ano no formato MM/AAAA.'
            if kind == 'time' and (
                len(value) != 5 or value[2] != ':' or not value[:2].isdigit()
                or not value[3:].isdigit() or int(value[:2]) > 23 or int(value[3:]) > 59
            ):
                return None, f'Informe um horário válido para {label.lower()}.'
            data[key] = value
        elif kind == 'employee':
            try:
                employee_id = int(value)
            except (TypeError, ValueError):
                return None, 'Selecione um colaborador válido.'
            with legacy.connect_db() as conn:
                if not conn.execute(
                    'SELECT 1 FROM funcionarios WHERE id = ?', (employee_id,)
                ).fetchone():
                    return None, 'O colaborador selecionado não existe.'
            data[key] = employee_id
        elif kind == 'number':
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None, f'Informe um valor numérico válido para {label.lower()}.'
            if number < 0:
                return None, f'O valor de {label.lower()} não pode ser negativo.'
            data[key] = number
        elif kind == 'positive_integer':
            try:
                number = int(value)
            except (TypeError, ValueError):
                return None, 'A carga horária deve ser um número inteiro maior que zero.'
            if number <= 0:
                return None, 'A carga horária deve ser um número inteiro maior que zero.'
            data[key] = number
    if module == 'vacations' and data['fim'] < data['inicio']:
        return None, 'A data final das férias deve ser igual ou posterior à inicial.'
    if module == 'payslips' and data['descontos'] > data['salario_bruto']:
        return None, 'Os descontos não podem ser maiores que o salário bruto.'
    return data, None


def _integrity_error(module, error):
    if module == 'trainings':
        return 'Já existe um treinamento com esse nome.'
    if 'FOREIGN KEY' in str(error).upper():
        return 'Confira se o colaborador selecionado ainda existe.'
    return 'Não foi possível salvar o registro por conflito com dados existentes.'


def run():
    port = int(os.environ.get('PORT', '5000'))
    application = create_app()
    threading.Timer(1, lambda: webbrowser.open(f'http://127.0.0.1:{port}')).start()
    application.run(host='127.0.0.1', port=port, debug=False)


if __name__ == '__main__':
    run()
