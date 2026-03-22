import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file
from flask_apscheduler import APScheduler
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, timedelta, date
import sqlite3
import json
from dotenv import load_dotenv
import psycopg2
import psycopg2.extras



load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')

# Configuração do APScheduler
scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

# =====================================================
# Funções Auxiliares e Inicialização do Banco de Dados
# =====================================================

def conectar_bd():
    try:
        conn = sqlite3.connect('financeiro.db')
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        flash(f"Erro ao conectar com o banco de dados: {e}", "danger")
        return None

def criar_admin_se_nao_existir(cursor):
    # Obtenha as credenciais do admin a partir das variáveis de ambiente
    admin_username = os.environ.get('ADMIN_USERNAME', None)
    admin_password = os.environ.get('ADMIN_PASSWORD', None)
    if admin_username is None or admin_password is None:
        print("Variáveis de ambiente ADMIN_USERNAME ou ADMIN_PASSWORD não definidas. Conta admin não será criada automaticamente.")
        return
    admin_password_hash = generate_password_hash(admin_password)
    cursor.execute("SELECT id FROM usuarios WHERE username = ?", (admin_username,))
    if cursor.fetchone() is None:
        cursor.execute("INSERT INTO usuarios (username, senha, role) VALUES (?, ?, ?)",
                       (admin_username, admin_password_hash, 'admin'))
        print("Conta admin criada com sucesso!")
    else:
        print("Conta admin já existe.")

def buscar_categorias_personalizadas(usuario_id):
    conn = conectar_bd()
    if not conn:
        return []
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM CategoriasPersonalizadas WHERE usuario_id = ? ORDER BY termo ASC", (usuario_id,))
    categorias = cursor.fetchall()
    conn.close()
    return categorias


def obter_categoria_por_termo(usuario_id, nome):
    if not nome:
        return None
    termo_busca = nome.strip().lower()
    conn = conectar_bd()
    if not conn:
        return None
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT categoria FROM CategoriasPersonalizadas WHERE usuario_id = ? AND LOWER(termo) = ?", (usuario_id, termo_busca))
    row = cursor.fetchone()
    if row:
        conn.close()
        return row['categoria']

    # Pesquisa parcial por termo contido no nome
    cursor.execute("SELECT categoria FROM CategoriasPersonalizadas WHERE usuario_id = ? AND ? LIKE '%' || LOWER(termo) || '%'", (usuario_id, termo_busca))
    row = cursor.fetchone()
    conn.close()
    return row['categoria'] if row else None


def inicializar_bd():
    conn = conectar_bd()
    if conn is None:
        return
    cursor = conn.cursor()

    # Verificar e adicionar coluna 'role' na tabela usuarios se não existir
    cursor.execute("PRAGMA table_info(usuarios);")
    colunas = [col[1] for col in cursor.fetchall()]
    if 'role' not in colunas:
        cursor.execute("ALTER TABLE usuarios ADD COLUMN role TEXT DEFAULT 'user'")
    
    try:
        cursor.execute("ALTER TABLE Transacoes ADD COLUMN categoria TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE Transacoes ADD COLUMN notificado INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE Transacoes ADD COLUMN notificado_antecipado INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE Transacoes ADD COLUMN usuario_id INTEGER")
    except sqlite3.OperationalError:
        pass

    # Criação da tabela de usuários com coluna role
    cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        senha TEXT NOT NULL,
        role TEXT DEFAULT 'user'
    )''')
    
    # Chama a função para criar a conta admin a partir das variáveis de ambiente
    criar_admin_se_nao_existir(cursor)

    # Criação da tabela Transacoes com a coluna usuario_id
    cursor.execute('''CREATE TABLE IF NOT EXISTS Transacoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        tipo TEXT NOT NULL,
        nome TEXT NOT NULL,
        valor REAL NOT NULL,
        periodo TEXT NOT NULL,
        categoria TEXT,
        data TEXT DEFAULT CURRENT_TIMESTAMP,
        notificado INTEGER DEFAULT 0,
        notificado_antecipado INTEGER DEFAULT 0
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS Configuracoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        investimento REAL DEFAULT 10.0,
        reserva REAL DEFAULT 10.0,
        causas_sociais REAL DEFAULT 10.0,
        lazer REAL DEFAULT 20.0,
        necessidades REAL DEFAULT 50.0
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS CategoriasPersonalizadas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        termo TEXT NOT NULL,
        categoria TEXT NOT NULL
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS Notificacoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mensagem TEXT NOT NULL,
        data_criacao TEXT DEFAULT CURRENT_TIMESTAMP,
        lida INTEGER DEFAULT 0
    )''')

    # A tabela Avisos registra contas a pagar ou a receber
    cursor.execute('''CREATE TABLE IF NOT EXISTS Avisos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        tipo TEXT NOT NULL, -- 'pagar' ou 'receber'
        nome TEXT NOT NULL,
        valor REAL NOT NULL,
        data DATE NOT NULL,
        status TEXT DEFAULT 'pendente'
    );''')

    cursor.execute('''INSERT INTO Configuracoes (investimento, reserva, causas_sociais, lazer, necessidades)
                      SELECT 10, 10, 10, 20, 50 WHERE NOT EXISTS (SELECT 1 FROM Configuracoes)''')
    conn.commit()
    conn.close()

# =====================================================
# Rotas de Autenticação (Login / Cadastro)
# =====================================================

@app.route('/')
def index():
    return render_template('login.html')

# Corrigir login com acesso seguro a 'role' mesmo sendo sqlite3.Row
@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']
    conn = sqlite3.connect('financeiro.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM usuarios WHERE username=?', (username,))
    user = cursor.fetchone()
    conn.close()
    if user and check_password_hash(user['senha'], password):
        session['user_id'] = user['id']
        session['role'] = user['role'] if 'role' in user.keys() else 'user'  # Correção segura
        if session['role'] == 'admin':
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('dashboard'))
    else:
        flash("Usuário ou Senha Inválidos", "error")
        return redirect(url_for('index'))
        
# Rota de cadastro para administradores (protegida por código de convite)
@app.route('/cadastro_admin', methods=['GET', 'POST'])
def cadastro_admin():
    # Verifica o código de convite passado como parâmetro ou via formulário
    convite = request.args.get('convite') or request.form.get('convite')
    convite_valido = os.environ.get('ADMIN_CONVITE', None)
    if convite_valido is None or convite != convite_valido:
        flash("Convite inválido para cadastro de administrador.", "error")
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirmPassword']
        if password != confirm_password:
            flash("As senhas não coincidem.", "error")
            return redirect(url_for('cadastro_admin', convite=convite))
        hashed_password = generate_password_hash(password)
        try:
            conn = sqlite3.connect('financeiro.db')
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM usuarios WHERE username = ?", (username,))
            if cursor.fetchone():
                flash("Este usuário já existe.", "error")
                return redirect(url_for('cadastro_admin', convite=convite))
            cursor.execute("INSERT INTO usuarios (username, senha, role) VALUES (?, ?, ?)",
                           (username, hashed_password, 'admin'))
            conn.commit()
            flash("Cadastro de administrador realizado com sucesso!", "success")
            return redirect(url_for('index'))
        except Exception as e:
            flash(f"Erro ao cadastrar administrador: {str(e)}", "error")
            return redirect(url_for('cadastro_admin', convite=convite))
        finally:
            conn.close()
    return render_template('cadastro_admin.html')


# Substitua a funcao `cadastro` por esta versao corrigida:
@app.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    # Cadastro de usuários comuns
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirmPassword']
        if password != confirm_password:
            flash("As senhas não coincidem. Por favor, insira senhas iguais.", "error")
            return redirect(url_for('cadastro'))
        hashed_password = generate_password_hash(password)
        try:
            conn = sqlite3.connect('financeiro.db')
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM usuarios WHERE username = ?", (username,))
            existing_user = cursor.fetchone()
            if existing_user:
                flash("Este usuário já existe. Por favor, escolha outro nome.", "error")
                return redirect(url_for('cadastro'))
            # Inserção com role explicita
            cursor.execute("INSERT INTO usuarios (username, senha, role) VALUES (?, ?, ?)", (username, hashed_password, 'user'))
            conn.commit()
            flash("Cadastro realizado com sucesso! Faça o login.", "success")
            return redirect(url_for('index'))
        except Exception as e:
            flash(f"Erro ao cadastrar usuário: {str(e)}", "error")
            return redirect(url_for('cadastro'))
        finally:
            conn.close()
    return render_template('cadastro.html')


# =====================================================
# Rotas para Dashboard e Administração
# =====================================================
@app.route('/dashboard')
def dashboard():

    if 'user_id' not in session or session.get('role') != 'user':
        flash("Você não está autenticado como usuário comum.", "error")
        return redirect(url_for('index'))

    try:

        conn = conectar_bd()

        if conn is None:
            flash("Erro ao conectar ao banco de dados", "danger")
            return redirect(url_for('index'))

        cursor = conn.cursor()


        # -----------------------------
        # TOTAL GERAL (SEM FILTRO DE DATA)
        # -----------------------------

        cursor.execute("""
            SELECT SUM(valor)
            FROM Transacoes
            WHERE usuario_id = ?
            AND LOWER(tipo) = 'renda'
        """, (session['user_id'],))

        total_rendas = cursor.fetchone()[0] or 0


        cursor.execute("""
            SELECT SUM(valor)
            FROM Transacoes
            WHERE usuario_id = ?
            AND LOWER(tipo) = 'gasto'
        """, (session['user_id'],))

        total_gastos = cursor.fetchone()[0] or 0


        saldo = round(total_rendas - total_gastos, 2)


        alerta_saldo = (
            "Seu saldo está negativo. Recomenda-se aumentar a renda ou reduzir os gastos."
            if saldo < 0 else ""
        )


        # -----------------------------
        # CONFIGURAÇÕES
        # -----------------------------

        cursor.execute(
            "SELECT * FROM Configuracoes LIMIT 1"
        )

        configuracoes = cursor.fetchone()


        categorias = [
            'necessidades',
            'lazer',
            'causas_sociais',
            'reserva',
            'investimento'
        ]


        # -----------------------------
        # METAS
        # -----------------------------

        metas = {

            cat:
                total_rendas *
                (configuracoes[cat] / 100)

            for cat in categorias

        }


        orientacao_gastos = {

            'investimento':
                "Investimento é importante para garantir renda futura.",

            'reserva':
                "Reserva de emergência é prioridade.",

            'causas_sociais':
                "Doações devem ser conscientes.",

            'lazer':
                "Controle gastos com lazer.",

            'necessidades':
                "Essenciais devem ser controlados."
        }


        # -----------------------------
        # GASTOS POR CATEGORIA (TOTAL)
        # -----------------------------

        gastos = {}

        for cat in categorias:

            cursor.execute("""

                SELECT SUM(valor)

                FROM Transacoes

                WHERE usuario_id = ?

                AND LOWER(tipo) = 'gasto'

                AND categoria = ?

            """, (session['user_id'], cat))

            gastos[cat] = cursor.fetchone()[0] or 0


        # -----------------------------
        # COMPARAÇÃO
        # -----------------------------

        comparacao = {

            cat: {

                "meta": metas[cat],

                "gasto": gastos[cat],

                "status":
                    "dentro"
                    if gastos[cat] <= metas[cat]
                    else "excedido"

            }

            for cat in categorias

        }


        # -----------------------------
        # GRÁFICO
        # -----------------------------

        cores = [
            '#4e73df',
            '#1cc88a',
            '#36b9cc',
            '#f6c23e',
            '#e74a3b'
        ]


        grafico_data = {

            'categorias':
                [c.capitalize() for c in categorias],

            'metas':
                [metas[c] for c in categorias],

            'gastos':
                [gastos[c] for c in categorias],

            'cores': cores,

            'cores_economia':
                [c + '33' for c in cores]

        }


        # -----------------------------
        # TODAS AS TRANSAÇÕES (SEM FILTRO)
        # -----------------------------

        cursor.execute("""

            SELECT *

            FROM Transacoes

            WHERE usuario_id = ?

            ORDER BY data DESC

        """, (session['user_id'],))

        transacoes = cursor.fetchall()


        conn.close()


        return render_template(

            'dashboard.html',

            saldo=saldo,

            metas={k: round(v, 2) for k, v in metas.items()},

            alerta_saldo=alerta_saldo,

            orientacao_gastos=orientacao_gastos,

            total_rendas=round(total_rendas, 2),

            total_gastos=round(total_gastos, 2),

            transacoes=transacoes,

            gastos={k: round(v, 2) for k, v in gastos.items()},

            comparacao=comparacao,

            grafico_data=json.dumps(grafico_data)

        )


    except Exception as e:

        flash(
            f"Erro ao carregar dashboard: {str(e)}",
            "error"
        )

        return redirect(url_for('index'))

@app.route('/admin_dashboard')
def admin_dashboard():
    if not admin_required():
        return redirect(url_for('index'))
    try:
        conn = sqlite3.connect('financeiro.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        search_username = request.args.get('username', '').strip().lower()
        search_role = request.args.get('role', '').strip().lower()

        query = "SELECT * FROM usuarios WHERE 1=1"
        params = []

        if search_username:
            query += " AND LOWER(username) LIKE ?"
            params.append(f"%{search_username}%")

        if search_role in ['admin', 'user']:
            query += " AND role = ?"
            params.append(search_role)

        query += " ORDER BY id DESC"

        cursor.execute(query, params)
        users = cursor.fetchall()
        conn.close()

        return render_template('admin_dashboard.html', users=users, search_username=search_username, search_role=search_role)
    except Exception as e:
        flash(f"Erro ao carregar dados administrativos: {str(e)}", "error")
        return redirect(url_for('index'))

@app.route('/categorias', methods=['GET', 'POST'])
def categorias():
    if 'user_id' not in session:
        flash('Ação requer login.', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        termo = request.form.get('termo', '').strip()
        categoria = request.form.get('categoria', '').strip().lower()

        if not termo or not categoria:
            flash('Preencha termo e categoria.', 'error')
            return redirect(url_for('categorias'))

        conn = conectar_bd()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO CategoriasPersonalizadas (usuario_id, termo, categoria) VALUES (?, ?, ?)',
                       (session['user_id'], termo, categoria))
        conn.commit()
        conn.close()

        flash('Categoria personalizada adicionada.', 'success')
        return redirect(url_for('categorias'))

    categorias_usuario = buscar_categorias_personalizadas(session['user_id'])
    return render_template('categorias.html', categorias=categorias_usuario)

@app.route('/categorias/excluir/<int:categoria_id>')
def excluir_categoria(categoria_id):
    if 'user_id' not in session:
        flash('Ação requer login.', 'error')
        return redirect(url_for('index'))

    conn = conectar_bd()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM CategoriasPersonalizadas WHERE id = ? AND usuario_id = ?',
                   (categoria_id, session['user_id']))
    conn.commit()
    conn.close()

    flash('Categoria personalizada removida.', 'success')
    return redirect(url_for('categorias'))

@app.route('/gestao_usuarios')
def gestao_usuarios():
    if not admin_required():
        return redirect(url_for('index'))
    search_username = request.args.get('username', '').strip().lower()
    search_role = request.args.get('role', '').strip().lower()

    conn = sqlite3.connect('financeiro.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = "SELECT * FROM usuarios WHERE 1=1"
    params = []

    if search_username:
        query += " AND LOWER(username) LIKE ?"
        params.append(f"%{search_username}%")

    if search_role in ['admin', 'user']:
        query += " AND role = ?"
        params.append(search_role)

    query += " ORDER BY id DESC"

    cursor.execute(query, params)
    users = cursor.fetchall()
    conn.close()

    return render_template('gestao_usuarios.html', users=users, search_username=search_username, search_role=search_role)

@app.route('/excluir_usuario/<int:user_id>')
def excluir_usuario(user_id):
    if not admin_required():
        return redirect(url_for('index'))

    if session.get('user_id') == user_id:
        flash("Você não pode excluir o próprio usuário.", "error")
        return redirect(url_for('gestao_usuarios'))

    conn = sqlite3.connect('financeiro.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM usuarios WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

    flash("Usuário excluído com sucesso.", "success")
    return redirect(url_for('gestao_usuarios'))

@app.route('/alterar_role_usuario/<int:user_id>', methods=['POST'])
def alterar_role_usuario(user_id):
    if not admin_required():
        return redirect(url_for('index'))

    nova_role = request.form.get('role')
    if nova_role not in ['admin', 'user']:
        flash("Role inválida.", "error")
        return redirect(url_for('gestao_usuarios'))

    conn = sqlite3.connect('financeiro.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE usuarios SET role = ? WHERE id = ?", (nova_role, user_id))
    conn.commit()
    conn.close()

    flash("Role de usuário atualizada com sucesso.", "success")
    return redirect(url_for('gestao_usuarios'))

# =====================================================
# Rotas de Transações, gestão e Metas
# =====================================================

# gestao_usuarios já definida anteriormente com controle de acesso, busca e edição.

@app.route('/transacoes', methods=['GET'])
def transacoes_view():
    if 'user_id' not in session:
        flash("Você não está autenticado.", "error")
        return redirect(url_for('index'))

    periodo = request.args.get('periodo', '').strip().lower()
    categoria = request.args.get('categoria', '').strip().lower()
    pesquisa = request.args.get('pesquisa', '').strip().lower()

    conn = conectar_bd()
    if conn is None:
        flash("Erro ao conectar ao banco de dados", "danger")
        return redirect(url_for('dashboard'))

    cursor = conn.cursor()
    query = "SELECT * FROM Transacoes WHERE usuario_id = ?"
    params = [session['user_id']]

    if periodo:
        query += " AND LOWER(periodo) = ?"
        params.append(periodo)

    if categoria and categoria != 'todas':
        query += " AND LOWER(categoria) = ?"
        params.append(categoria)

    if pesquisa:
        query += " AND (LOWER(nome) LIKE ? OR LOWER(tipo) LIKE ? OR LOWER(categoria) LIKE ? OR LOWER(periodo) LIKE ?)"
        wildcard = f"%{pesquisa}%"
        params.extend([wildcard, wildcard, wildcard, wildcard])

    query += " ORDER BY data DESC"
    cursor.execute(query, params)
    transacoes = cursor.fetchall()
    conn.close()

    return render_template('transacoes.html', transacoes=transacoes, periodo=periodo, pesquisa=pesquisa, categoria=categoria)

def notificar_transacoes():
    conn = conectar_bd()
    cursor = conn.cursor()
    hoje = datetime.now().strftime('%Y-%m-%d')
    
    # Buscar transações do dia
    cursor.execute("""
        SELECT usuario_id, nome, valor, categoria
        FROM Transacoes
        WHERE data = ?
    """, (hoje,))
    
    transacoes = cursor.fetchall()
    conn.close()
    
    # Exibir alerta simples
    if transacoes:
        print("Transações do dia:")
        for usuario_id, nome, valor, categoria in transacoes:
            print(f"Usuário {usuario_id}: {nome} - {categoria} - R$ {valor:.2f}")


@app.route('/adicionar_transacao', methods=['GET', 'POST'])
def adicionar_transacao():
    if request.method == 'POST':

        tipo = request.form.get('tipo', '').strip().lower()
        nome = request.form.get('nome')
        valor = request.form.get('valor')
        data = request.form.get('data')

        # Campos obrigatórios
        if not tipo or not nome or not valor or not data:
            return "Erro: campos obrigatórios faltando", 400

        try:
            valor = float(valor)
        except:
            return "Erro: valor inválido", 400

        categoria_form = request.form.get('categoria', '').strip().lower()

        # Regras para RENDA
        if tipo == 'renda':
            periodo = ""              # 🔥 evita erro do banco (NOT NULL)
            categoria = 'renda'

        # Regras para GASTO
        else:
            periodo = request.form.get('periodo')
            if not periodo:
                return "Erro: período é obrigatório para gastos", 400

            if categoria_form and categoria_form != 'auto':
                categoria = categoria_form
            else:
                categoria = obter_categoria_por_termo(session['user_id'], nome) or 'necessidades'

        # Inserção no banco
        conn = conectar_bd()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO Transacoes (usuario_id, tipo, nome, valor, periodo, categoria, data)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (session['user_id'], tipo, nome, valor, periodo, categoria, data))

        conn.commit()
        conn.close()

        flash("Transação adicionada com sucesso!", "success")
        return redirect(url_for('transacoes_view'))

    return render_template('adicionar_transacao.html')


@app.route('/editar_transacao/<int:id>', methods=['GET', 'POST'])
def editar_transacao(id):
    conn = conectar_bd()
    cursor = conn.cursor()

    if request.method == 'POST':

        tipo = request.form.get('tipo', '').strip().lower()
        nome = request.form.get('nome')
        valor = request.form.get('valor')
        data = request.form.get('data')

        if not tipo or not nome or not valor or not data:
            return "Erro: campos obrigatórios faltando", 400

        try:
            valor = float(valor)
        except:
            return "Erro: valor inválido", 400

        # Renda → sem período e sem categoria
        if tipo == 'renda':
            periodo = None
            categoria = 'renda'

        else:
            periodo = request.form.get('periodo')
            categoria_form = request.form.get('categoria', '').strip().lower()

            if not periodo:
                return "Erro: período obrigatório para gastos", 400

            if categoria_form and categoria_form != 'auto':
                categoria = categoria_form
            else:
                categoria = obter_categoria_por_termo(session['user_id'], nome) or 'necessidades'

        cursor.execute("""
            UPDATE Transacoes
            SET tipo = ?, nome = ?, valor = ?, periodo = ?, categoria = ?, data = ?
            WHERE id = ? AND usuario_id = ?
        """, (tipo, nome, valor, periodo, categoria, data, id, session['user_id']))

        conn.commit()
        conn.close()

        flash("Transação atualizada com sucesso!", "success")
        return redirect(url_for('transacoes_view'))

    cursor.execute("SELECT * FROM Transacoes WHERE id = ? AND usuario_id = ?", (id, session['user_id']))
    transacao = cursor.fetchone()
    conn.close()

    return render_template('editar_transacao.html', transacao=transacao)

@app.route('/excluir_transacao/<int:id>', methods=['GET'])
def excluir_transacao(id):
    conn = conectar_bd()
    if conn is None:
        flash("Erro ao conectar ao banco de dados", "danger")
        return redirect(url_for('index'))
    cursor = conn.cursor()
    cursor.execute("DELETE FROM Transacoes WHERE id = ? AND usuario_id = ?", (id, session['user_id']))
    conn.commit()
    conn.close()
    flash("Transação excluída com sucesso!", "success")
    return redirect(url_for('transacoes_view'))


# =====================================================
# Rotas para Avisos (Contas a Pagar / Receber)
# =====================================================

@app.route('/inserir_aviso', methods=['GET', 'POST'])
def inserir_aviso():
    if 'user_id' not in session:
        flash("Você não está autenticado.", "error")
        return redirect(url_for('index'))
    if request.method == 'POST':
        usuario_id = session['user_id']
        tipo = request.form['tipo'].strip().lower()  # 'pagar' ou 'receber'
        nome = request.form['nome']
        valor = float(request.form['valor'])
        data = request.form['data']
        conn = conectar_bd()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO Avisos (usuario_id, tipo, nome, valor, data, status) VALUES (?, ?, ?, ?, ?, ?)",
                       (usuario_id, tipo, nome, valor, data, 'Pendente'))
        conn.commit()
        conn.close()
        flash("Aviso inserido com sucesso!", "success")
        return redirect(url_for('contas'))
    return render_template('inserir_aviso.html')


@app.route('/contas')
def contas():
    if 'user_id' not in session:
        flash("Você não está autenticado.", "error")
        return redirect(url_for('index'))

    periodo = request.args.get('periodo', '').strip()
    pesquisa = request.args.get('pesquisa', '').strip().lower()
    tipo = request.args.get('tipo', '').strip().lower()

    conn = conectar_bd()
    cursor = conn.cursor()

    query = "SELECT * FROM Avisos WHERE usuario_id = ?"
    params = [session['user_id']]

    if periodo:
        query += " AND data LIKE ?"
        params.append(f"%{periodo}%")

    if tipo and tipo != 'todos':
        query += " AND LOWER(tipo) = ?"
        params.append(tipo)

    if pesquisa:
        query += " AND (LOWER(nome) LIKE ? OR LOWER(tipo) LIKE ? OR LOWER(status) LIKE ?)"
        wildcard = f"%{pesquisa}%"
        params.extend([wildcard, wildcard, wildcard])

    query += " ORDER BY data ASC"
    cursor.execute(query, params)
    avisos = cursor.fetchall()
    conn.close()

    hoje = date.today().isoformat()
    return render_template('contas.html', avisos=avisos, hoje=hoje, periodo=periodo, pesquisa=pesquisa, tipo=tipo)


@app.route('/excluir_aviso/<int:id>')
def excluir_aviso(id):
    if 'user_id' not in session:
        return redirect(url_for('index'))

    conn = conectar_bd()
    cur = conn.cursor()

    cur.execute("DELETE FROM Avisos WHERE id = ? AND usuario_id = ?", (id, session['user_id']))

    conn.commit()
    conn.close()

    flash("Aviso excluído!", "success")
    return redirect(url_for('contas'))


@app.route('/atualizar_status_em_lote', methods=['POST'])
def atualizar_status_em_lote():
    try:
        status_updates = request.get_json()
        conn = conectar_bd()
        cursor = conn.cursor()

        for update in status_updates:
            id_ = update['id']
            novo_status = update['status']

            # Atualiza status do aviso
            cursor.execute("UPDATE Avisos SET status = ? WHERE id = ?", (novo_status, id_))

            # Se status for 'Pago', cria transação correspondente
            if novo_status == 'Pago':
                aviso = cursor.execute("SELECT * FROM Avisos WHERE id = ?", (id_,)).fetchone()

                # Converte tipo do aviso para tipo de transação
                tipo_transacao = 'renda' if aviso['tipo'] == 'receber' else 'gasto'
                categoria = 'Aviso Pago'
                periodo = aviso['data'] if tipo_transacao == 'gasto' else None

                # Insere transação
                cursor.execute(
                    "INSERT INTO Transacoes (usuario_id, tipo, nome, valor, data, categoria, periodo) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (aviso['usuario_id'], tipo_transacao, aviso['nome'], aviso['valor'], aviso['data'], categoria, periodo)
                )

        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'Status atualizados com sucesso!'})
    
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

# =====================================================
# Rotas para Editar Metas
# =====================================================

@app.route('/editar_metas', methods=['GET', 'POST'])
def editar_metas():
    conn = conectar_bd()
    if conn is None:
        flash("Erro ao conectar ao banco de dados", "danger")
        return redirect(url_for('index'))
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Configuracoes LIMIT 1")
    configuracoes = cursor.fetchone()
    if request.method == 'POST':
        investimento = float(request.form['investimento'])
        reserva = float(request.form['reserva'])
        causas_sociais = float(request.form['causas_sociais'])
        lazer = float(request.form['lazer'])
        necessidades = float(request.form['necessidades'])
        cursor.execute("UPDATE Configuracoes SET investimento = ?, reserva = ?, causas_sociais = ?, lazer = ?, necessidades = ? WHERE id = 1",
                       (investimento, reserva, causas_sociais, lazer, necessidades))
        conn.commit()
        conn.close()
        flash("Metas atualizadas com sucesso!", "success")
        return redirect(url_for('dashboard'))
    conn.close()
    return render_template('editar_metas.html', configuracoes=configuracoes)

# =====================================================
# Rotas para Calendário (Exibição de Eventos)
# =====================================================

@app.route("/calendario")
def calendario():

    if "user_id" not in session:
        flash("Você não está autenticado.", "error")
        return redirect(url_for("index"))

    conn = conectar_bd()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    tipo = request.args.get("tipo", "intervalo")

    categoria_filtro = request.args.get("categoria", "")
    busca = request.args.get("busca", "")

    hoje = date.today()

    inicio = request.args.get("inicio")
    fim = request.args.get("fim")
    dia = request.args.get("dia")
    mes = request.args.get("mes")
    ano = request.args.get("ano")
    semana = request.args.get("semana")

    dt_inicio = hoje
    dt_fim = hoje


    # -------------------
    # INTERVALO
    # -------------------

    if tipo == "intervalo" and inicio and fim:

        dt_inicio = datetime.strptime(
            inicio,
            "%Y-%m-%d"
        ).date()

        dt_fim = datetime.strptime(
            fim,
            "%Y-%m-%d"
        ).date()


    elif tipo == "diario":

        d = dia or hoje.strftime("%Y-%m-%d")

        dt_inicio = dt_fim = datetime.strptime(
            d,
            "%Y-%m-%d"
        ).date()


    elif tipo == "semanal":

        semana = semana or hoje.strftime("%Y-W%W")

        ano_s, sem_s = semana.split("-W")

        dt_inicio = datetime.fromisocalendar(
            int(ano_s),
            int(sem_s),
            1
        ).date()

        dt_fim = datetime.fromisocalendar(
            int(ano_s),
            int(sem_s),
            7
        ).date()


    elif tipo == "mensal":

        mes = mes or hoje.strftime("%Y-%m")

        ano_m, mes_m = map(int, mes.split("-"))

        dt_inicio = date(ano_m, mes_m, 1)

        if mes_m < 12:
            dt_fim = date(
                ano_m,
                mes_m + 1,
                1
            ) - timedelta(days=1)
        else:
            dt_fim = date(ano_m, 12, 31)


    elif tipo == "anual":

        ano = int(ano or hoje.year)

        dt_inicio = date(ano, 1, 1)
        dt_fim = date(ano, 12, 31)


    # -------------------
    # QUERY
    # -------------------

    query = """
        SELECT tipo, valor, categoria, nome, data
        FROM Transacoes
        WHERE usuario_id = ?
        AND DATE(data) BETWEEN ? AND ?
    """

    params = [
        session["user_id"],
        dt_inicio,
        dt_fim
    ]


    # filtro categoria

    if categoria_filtro and categoria_filtro != "todas":

        query += " AND categoria = ?"

        params.append(categoria_filtro)


    # filtro busca

    if busca:

        query += " AND nome LIKE ?"

        params.append(f"%{busca}%")


    cursor.execute(query, params)

    transacoes = cursor.fetchall()


    # -------------------
    # TOTAIS
    # -------------------

    total_rendas = sum(
        t["valor"]
        for t in transacoes
        if t["tipo"].lower() == "renda"
    )

    total_gastos = sum(
        t["valor"]
        for t in transacoes
        if t["tipo"].lower() == "gasto"
    )

    saldo = total_rendas - total_gastos


    # -------------------
    # CONFIG
    # -------------------

    cursor.execute(
        "SELECT * FROM Configuracoes LIMIT 1"
    )

    row = cursor.fetchone()

    config = dict(row) if row else {}


    categorias = [
        "necessidades",
        "lazer",
        "causas_sociais",
        "reserva",
        "investimento"
    ]


    metas = {

        c:
        total_rendas *
        (config.get(c, 0) / 100)

        for c in categorias

    }


    gastos = {c: 0 for c in categorias}


    for t in transacoes:

        if (
            t["tipo"] == "gasto"
            and t["categoria"] in gastos
        ):
            gastos[t["categoria"]] += t["valor"]


    comparacao = {

        c: {

            "meta": metas[c],

            "gasto": gastos[c],

            "status":
                "dentro"
                if gastos[c] <= metas[c]
                else "excedido"

        }

        for c in categorias

    }


    grafico_data = json.dumps({

        "categorias":
            [c.capitalize() for c in categorias],

        "gastos":
            [gastos[c] for c in categorias],

        "metas":
            [metas[c] for c in categorias]

    })


    conn.close()


    return render_template(

    "calendario.html",

    total_rendas=total_rendas,
    total_gastos=total_gastos,
    saldo=saldo,

    comparacao=comparacao,
    grafico_data=grafico_data,

    dt_inicio=dt_inicio,
    dt_fim=dt_fim,

    tipo=tipo,

    categoria=categoria_filtro,
    busca=busca,

    categorias=categorias,

    transacoes=transacoes,   
    
    filtro_ativo=True
)

@app.route("/logout")
def logout():
    session.clear()
    flash("Logout realizado", "success")
    return redirect(url_for("index"))
# =====================================================
# Execução do Aplicativo (LOCAL APENAS)
# =====================================================
if __name__ == '__main__':
    inicializar_bd()
    app.run(host='0.0.0.0', port=5000)
