import json
import tempfile
import unittest
from pathlib import Path

import main as legacy
from web_app import create_app


class WebApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = legacy.DB_PATH
        self.original_settings_path = legacy.SETTINGS_PATH
        legacy.DB_PATH = Path(self.temp_dir.name) / 'test.db'
        legacy.SETTINGS_PATH = Path(self.temp_dir.name) / 'settings.json'
        legacy.init_db()
        legacy.ensure_seed_data()
        legacy.ensure_training_seed_data()
        self.client = create_app({
            'TESTING': True,
            'SECRET_KEY': 'test-session-key',
        }).test_client()
        self.csrf = self.client.get('/api/session').get_json()['csrf_token']

    def tearDown(self):
        legacy.DB_PATH = self.original_db_path
        legacy.SETTINGS_PATH = self.original_settings_path
        self.temp_dir.cleanup()

    def headers(self):
        return {'X-CSRF-Token': self.csrf}

    def create_admin(self):
        response = self.client.post(
            '/api/auth/setup',
            json={
                'username': 'admin',
                'password': 'long-enough-password',
                'confirmation': 'long-enough-password',
            },
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 201)
        self.csrf = self.client.get('/api/session').get_json()['csrf_token']

    def test_initial_setup_and_employee_crud_preserve_schema(self):
        self.create_admin()
        response = self.client.post(
            '/api/modules/employees',
            json={
                'nome': 'Beatriz Lima',
                'cargo': 'Analista',
                'setor': 'Pessoas',
                'salario': 5200,
            },
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 201)
        employee_id = response.get_json()['id']

        response = self.client.get('/api/modules/employees')
        self.assertEqual(response.status_code, 200)
        created = next(row for row in response.get_json()['rows'] if row['id'] == employee_id)
        self.assertEqual(created['nome'], 'Beatriz Lima')

        response = self.client.patch(
            f'/api/modules/employees/{employee_id}',
            json={
                'nome': 'Beatriz Costa',
                'cargo': 'Coordenadora',
                'setor': 'Pessoas',
                'salario': 5900,
            },
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.delete(
            f'/api/modules/employees/{employee_id}',
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 200)
        with legacy.connect_db() as conn:
            self.assertEqual(
                conn.execute(
                    'SELECT COUNT(*) FROM funcionarios WHERE id = ?', (employee_id,)
                ).fetchone()[0],
                0,
            )

    def test_validation_training_enrollment_and_vacation_status(self):
        self.create_admin()
        invalid = self.client.post(
            '/api/modules/employees',
            json={'nome': 'Inválido', 'cargo': 'Cargo', 'setor': 'Setor', 'salario': -1},
            headers=self.headers(),
        )
        self.assertEqual(invalid.status_code, 400)

        courses = self.client.get('/api/modules/trainings').get_json()['rows']
        course_id = courses[0]['id']
        enrollment = self.client.post(
            f'/api/trainings/{course_id}/enrollments',
            json={'funcionario_id': 3},
            headers=self.headers(),
        )
        self.assertEqual(enrollment.status_code, 201)
        self.assertEqual(
            len(self.client.get(f'/api/trainings/{course_id}/enrollments').get_json()),
            1,
        )

        with legacy.connect_db() as conn:
            vacation_id = conn.execute('SELECT id FROM ferias LIMIT 1').fetchone()[0]
        completed = self.client.post(
            f'/api/vacations/{vacation_id}/complete',
            json={},
            headers=self.headers(),
        )
        self.assertEqual(completed.status_code, 200)
        with legacy.connect_db() as conn:
            status = conn.execute(
                'SELECT status FROM ferias WHERE id = ?', (vacation_id,)
            ).fetchone()['status']
        self.assertEqual(status, 'Cumprido')

    def test_login_and_settings_are_persisted(self):
        self.create_admin()
        logout = self.client.post(
            '/api/auth/logout',
            headers=self.headers(),
            json={},
        )
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(self.client.get('/api/dashboard').status_code, 401)
        self.csrf = self.client.get('/api/session').get_json()['csrf_token']
        response = self.client.post(
            '/api/auth/login',
            json={'username': 'admin', 'password': 'long-enough-password'},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.csrf = self.client.get('/api/session').get_json()['csrf_token']
        response = self.client.patch(
            '/api/settings',
            json={'theme': 'dark'},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 200)
        saved = json.loads(legacy.SETTINGS_PATH.read_text(encoding='utf-8'))
        self.assertEqual(saved['theme'], 'dark')
        self.assertIsNone(saved['database_directory'])

    def test_remaining_hr_modules_and_admin_accounts(self):
        self.create_admin()
        employee_id = 1
        requests = [
            ('dependents', {
                'funcionario_id': employee_id,
                'nome': 'Dependente Smoke',
                'parentesco': 'Filho(a)',
            }),
            ('payslips', {
                'funcionario_id': employee_id,
                'mes_ano': '11/2026',
                'salario_bruto': 4500,
                'descontos': 250,
            }),
            ('attendance', {
                'funcionario_id': employee_id,
                'data': '2026-10-27',
                'entrada': '08:00',
                'saida': '17:00',
            }),
            ('vacations', {
                'funcionario_id': employee_id,
                'inicio': '2027-01-10',
                'fim': '2027-01-24',
            }),
            ('trainings', {
                'titulo': 'Treinamento Smoke API',
                'categoria': 'Operacional',
                'carga_horaria': 8,
                'modalidade': 'EAD',
            }),
        ]
        created = {}
        for module, payload in requests:
            response = self.client.post(
                f'/api/modules/{module}',
                json=payload,
                headers=self.headers(),
            )
            self.assertEqual(response.status_code, 201, response.get_json())
            created[module] = response.get_json()['id']

        with legacy.connect_db() as conn:
            payslip = conn.execute(
                'SELECT salario_liquido FROM contracheques WHERE id = ?',
                (created['payslips'],),
            ).fetchone()
        self.assertEqual(payslip['salario_liquido'], 4250)
        payslip_report = self.client.get('/api/modules/payslips').get_json()['rows']
        self.assertIn('cargo', payslip_report[0])
        self.assertIn('setor', payslip_report[0])
        attendance_report = self.client.get('/api/modules/attendance').get_json()['rows']
        self.assertIn('cargo', attendance_report[0])
        vacations_report = self.client.get('/api/modules/vacations').get_json()['rows']
        self.assertIn('setor', vacations_report[0])
        self.assertEqual(
            self.client.get('/api/modules/departments').status_code,
            200,
        )
        self.assertEqual(
            self.client.get('/api/modules/positions').status_code,
            200,
        )

        user = self.client.post(
            '/api/modules/users',
            json={
                'username': 'rh-user',
                'password': 'valid-password',
                'role': 'Usuário',
            },
            headers=self.headers(),
        )
        self.assertEqual(user.status_code, 201)
        self.assertEqual(
            self.client.get('/api/modules/users').status_code,
            200,
        )


if __name__ == '__main__':
    unittest.main()
