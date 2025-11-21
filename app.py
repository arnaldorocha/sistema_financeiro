import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file
from flask_apscheduler import APScheduler
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, timedelta, date
import sqlite3
import json
from dotenv import load_dotenv



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
         # Dados do mês atual
        data_inicio = datetime.now().replace(day=1).strftime('%Y-%m-%d')
        data_fim = (datetime.now().replace(day=28) + timedelta(days=4)).replace(day=1).strftime('%Y-%m-%d')
        relatorio_datas = {'inicio': data_inicio, 'fim': data_fim}
    
        conn = conectar_bd()
        if conn is None:
            flash("Erro ao conectar ao banco de dados", "danger")
            return redirect(url_for('index'))
      
        cursor = conn.cursor()
        # Filtra transações do mês atual para o usuário autenticado
      
        cursor.execute("""
            SELECT * FROM Transacoes 
            WHERE usuario_id = ? 
            AND data BETWEEN ? AND ?
            ORDER BY data DESC
        """, (session['user_id'], data_inicio, data_fim))

        transacoes = cursor.fetchall()

        cursor.execute("SELECT * FROM Configuracoes LIMIT 1")
        configuracoes = cursor.fetchone()

        # Total renda e total gasto
        cursor.execute("""
            SELECT SUM(valor) 
            FROM Transacoes 
            WHERE usuario_id = ? 
            AND LOWER(tipo) = 'renda'
            AND data BETWEEN ? AND ?
        """, (session['user_id'], data_inicio, data_fim))
        total_rendas = cursor.fetchone()[0] or 0
      
        cursor.execute("""
            SELECT SUM(valor) 
            FROM Transacoes 
            WHERE usuario_id = ? 
            AND LOWER(tipo) = 'gasto'
            AND data BETWEEN ? AND ?
        """, (session['user_id'], data_inicio, data_fim))
        total_gastos = cursor.fetchone()[0] or 0

        saldo = round(total_rendas - total_gastos, 2)
        alerta_saldo = "Seu saldo está negativo. Recomenda-se aumentar a renda ou reduzir os gastos." if saldo < 0 else ""
        metas = {
            'investimento': total_rendas * (configuracoes['investimento'] / 100),
            'reserva': total_rendas * (configuracoes['reserva'] / 100),
            'causas_sociais': total_rendas * (configuracoes['causas_sociais'] / 100),
            'lazer': total_rendas * (configuracoes['lazer'] / 100),
            'necessidades': total_rendas * (configuracoes['necessidades'] / 100)
        }
        orientacao_gastos = {
            'investimento': "Investimento é importante para garantir uma renda extra.",
            'reserva': "Uma reserva de emergência é crucial. Não use este valor para despesas do dia a dia.",
            'causas_sociais': "Doações são uma ótima forma de ajudar. Destine esse valor com consciência.",
            'lazer': "Lazer é importante, mas não ultrapasse sua meta para não comprometer outras necessidades.",
            'necessidades': "Esses gastos são essenciais, mas sempre busque eficiência e evite excessos."
        }
        categorias = ['necessidades', 'lazer', 'causas_sociais', 'reserva', 'investimento']
        gastos = {}
        for cat in categorias:
            cursor.execute("""
                SELECT SUM(valor) 
                FROM Transacoes 
                WHERE usuario_id = ?
                AND LOWER(tipo) = 'gasto'
                AND categoria = ?
                AND data BETWEEN ? AND ?
            """, (session['user_id'], cat.lower(), data_inicio, data_fim))
            gastos[cat] = cursor.fetchone()[0] or 0
        comparacao = {cat: {
                "meta": metas[cat],
                "gasto": gastos[cat],
                "status": "dentro" if gastos[cat] <= metas[cat] else "excedido"
            } for cat in categorias}
        cores = ['#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b']
        grafico_data = {
            'categorias': [cat.capitalize() for cat in categorias],
            'metas': [metas[cat] for cat in categorias],
            'gastos': [gastos[cat] for cat in categorias],
            'cores': cores,
            'cores_economia': [c + '33' for c in cores]
        }
        conn.close()
        return render_template('dashboard.html',
                               relatorio_datas=relatorio_datas,
                               saldo=saldo,
                               metas={k: round(v, 2) for k, v in metas.items()},
                               alerta_saldo=alerta_saldo,
                               orientacao_gastos=orientacao_gastos,
                               total_rendas=round(total_rendas, 2),
                               total_gastos=round(total_gastos, 2),
                               transacoes=transacoes,
                               gastos={k: round(v, 2) for k, v in gastos.items()},
                               comparacao=comparacao,
                               grafico_data=json.dumps(grafico_data))
    except Exception as e:
        flash(f"Erro ao carregar transações: {str(e)}", "error")
        return redirect(url_for('index'))

@app.route('/admin_dashboard')
def admin_dashboard():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash("Acesso negado.", "error")
        return redirect(url_for('index'))
    try:
        conn = sqlite3.connect('financeiro.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM usuarios")
        users = cursor.fetchall()
        conn.close()
        return render_template('admin_dashboard.html', users=users)
    except Exception as e:
        flash(f"Erro ao carregar dados administrativos: {str(e)}", "error")
        return redirect(url_for('index'))

# =====================================================
# Rotas de Transações, gestão e Metas
# =====================================================

@app.route('/gestao_usuarios')
def gestao_usuarios():
    return render_template('gestao_usuarios.html')

@app.route('/transacoes', methods=['GET'])
def transacoes_view():
    if 'user_id' not in session:
        flash("Você não está autenticado.", "error")
        return redirect(url_for('index'))
    periodo = request.args.get('periodo')
    pesquisa = request.args.get('pesquisa', '').lower()
    conn = conectar_bd()
    if conn is None:
        flash("Erro ao conectar ao banco de dados", "danger")
        return redirect(url_for('dashboard'))
    cursor = conn.cursor()
    if periodo:
        cursor.execute("SELECT * FROM Transacoes WHERE usuario_id = ? AND periodo = ? ORDER BY data DESC", (session['user_id'], periodo))
    else:
        cursor.execute("SELECT * FROM Transacoes WHERE usuario_id = ? ORDER BY data DESC", (session['user_id'],))
    transacoes = cursor.fetchall()
    conn.close()
    if pesquisa:
        transacoes = [t for t in transacoes if pesquisa in t['nome'].lower()]
    return render_template('transacoes.html', transacoes=transacoes, periodo=periodo, pesquisa=pesquisa)

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

        # Validação comum
        if not tipo or not nome or not valor or not data:
            return "Erro: campos obrigatórios faltando", 400

        try:
            valor = float(valor)
        except:
            return "Erro: valor inválido", 400

        # Regras especiais para Renda
        if tipo == 'renda':
            periodo = None
            categoria = 'renda'

        # Regras para Gasto
        else:
            periodo = request.form.get('periodo')
            categoria = request.form.get('categoria')

            if not periodo:
                return "Erro: período obrigatório para gastos", 400
            if not categoria:
                return "Erro: categoria obrigatória para gastos", 400

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
            categoria = request.form.get('categoria')

            if not periodo:
                return "Erro: período obrigatório para gastos", 400
            if not categoria:
                return "Erro: categoria obrigatória para gastos", 400

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
        if conn is None:
            flash("Erro ao conectar ao banco de dados", "danger")
            return redirect(url_for('index'))
        cursor = conn.cursor()
        cursor.execute("INSERT INTO Avisos (usuario_id, tipo, nome, valor, data) VALUES (?, ?, ?, ?, ?)",
                       (usuario_id, tipo, nome, valor, data))
        conn.commit()
        conn.close()
        flash("Aviso inserido com sucesso!", "success")
        return redirect(url_for('contas'))
    return render_template('inserir_aviso.html')

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
# Rotas para Contas (Exibição de Contas a Pagar/Receber)
# =====================================================

@app.route('/contas')
def contas():
    if 'user_id' not in session:
        flash("Você não está autenticado.", "error")
        return redirect(url_for('index'))
    periodo = request.args.get('periodo')
    pesquisa = request.args.get('pesquisa', '').lower()
    conn = conectar_bd()
    if conn is None:
        flash("Erro ao conectar ao banco de dados", "danger")
        return redirect(url_for('dashboard'))
    cursor = conn.cursor()
    if periodo:
        cursor.execute("SELECT * FROM Avisos WHERE usuario_id = ? AND data LIKE ? ORDER BY data ASC", (session['user_id'], f'%{periodo}%'))
    else:
        cursor.execute("SELECT * FROM Avisos WHERE usuario_id = ? ORDER BY data ASC", (session['user_id'],))
    avisos = cursor.fetchall()
    conn.close()
    if pesquisa:
        avisos = [a for a in avisos if pesquisa in a['nome'].lower() or pesquisa in a['tipo'].lower()]
    hoje = date.today().isoformat()  # 'YYYY-MM-DD'
    return render_template('contas.html', avisos=avisos, hoje=hoje)
@app.route('/atualizar_status', methods=['POST'])
def atualizar_status():
    id_ = request.form['id']
    novo_status = request.form['status']
    conn = conectar_bd()
    cursor = conn.cursor()

    # Atualiza o status do aviso
    cursor.execute("UPDATE Avisos SET status = ? WHERE id = ?", (novo_status, id_))

    # Se o status for 'Pago', cria uma nova transação
    if novo_status == 'Pago':
        # Recupera as informações do aviso
        aviso = cursor.execute("SELECT * FROM Avisos WHERE id = ?", (id_,)).fetchone()

        # Adiciona uma nova transação com as informações do aviso
        cursor.execute(
            "INSERT INTO Transacoes (usuario_id, tipo, nome, valor, data, categoria) VALUES (?, ?, ?, ?, ?, ?)",
            (aviso['usuario_id'], aviso['tipo'], aviso['nome'], aviso['valor'], aviso['data'], 'Conta Paga')
        )

    # Commit para salvar as mudanças
    conn.commit()
    conn.close()

    # Redireciona para a página de transações, onde a nova transação será exibida
    return redirect(url_for('transacoes_view'))

@app.route('/atualizar_status_em_lote', methods=['POST'])
def atualizar_status_em_lote():
    try:
        # Receber os dados enviados em JSON
        status_updates = request.get_json()

        # Estabelecer a conexão com o banco de dados
        conn = conectar_bd()
        cursor = conn.cursor()

        # Para cada atualização de status recebida, realiza a mudança no banco de dados
        for update in status_updates:
            id_ = update['id']
            novo_status = update['status']

            # Atualiza o status do aviso
            cursor.execute("UPDATE Avisos SET status = ? WHERE id = ?", (novo_status, id_))

            # Se o status for 'Pago', cria uma nova transação
            if novo_status == 'Pago':
                # Recupera as informações do aviso
                aviso = cursor.execute("SELECT * FROM Avisos WHERE id = ?", (id_,)).fetchone()

                # Adiciona uma nova transação com as informações do aviso
                cursor.execute(
                    "INSERT INTO Transacoes (usuario_id, tipo, nome, valor, data, categoria) VALUES (?, ?, ?, ?, ?, ?)",
                    (aviso['usuario_id'], aviso['tipo'], aviso['nome'], aviso['valor'], aviso['data'], 'Conta Paga')
                )

        # Commit para salvar as mudanças no banco
        conn.commit()
        conn.close()

        return jsonify({'success': True, 'message': 'Status atualizados com sucesso!'})
    
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

# =====================================================
# Rotas para Calendário (Exibição de Eventos)
# =====================================================

@app.route("/calendario")
def calendario():

    if "user_id" not in session:
        flash("Você não está autenticado.", "error")
        return redirect(url_for("index"))

    # Tipo de filtro escolhido
    tipo = request.args.get("tipo", "intervalo")

    # Valores recebidos
    inicio = request.args.get("inicio")
    fim = request.args.get("fim")
    dia = request.args.get("dia")
    mes = request.args.get("mes")
    ano = request.args.get("ano")
    semana = request.args.get("semana")

    today = date.today()

    # ===============================
    # 1 — INTERVALO LIVRE
    # ===============================
    if tipo == "intervalo" and inicio and fim:
        dt_inicio = datetime.strptime(inicio, "%Y-%m-%d").date()
        dt_fim = datetime.strptime(fim, "%Y-%m-%d").date()

    # ===============================
    # 2 — DIÁRIO
    # ===============================
    elif tipo == "diario":
        if not dia:
            dia = today.strftime("%Y-%m-%d")
        dt_inicio = datetime.strptime(dia, "%Y-%m-%d").date()
        dt_fim = dt_inicio

    # ===============================
    # 3 — SEMANAL
    # ===============================
    elif tipo == "semanal":
        if not semana:
            semana = today.strftime("%Y-W%W")  # semana ISO atual

        ano_sem, semana_sem = semana.split("-W")
        ano_sem = int(ano_sem)
        semana_sem = int(semana_sem)

        # Semana ISO começa na segunda
        dt_inicio = datetime.fromisocalendar(ano_sem, semana_sem, 1).date()
        dt_fim = datetime.fromisocalendar(ano_sem, semana_sem, 7).date()

    # ===============================
    # 4 — MENSAL
    # ===============================
    elif tipo == "mensal":
        if not mes:
            mes = today.strftime("%Y-%m")

        ano_m, mes_m = mes.split("-")
        ano_m = int(ano_m)
        mes_m = int(mes_m)

        dt_inicio = date(ano_m, mes_m, 1)

        # Último dia do mês
        if mes_m == 12:
            dt_fim = date(ano_m, 12, 31)
        else:
            dt_fim = date(ano_m, mes_m + 1, 1) - timedelta(days=1)

    # ===============================
    # 5 — ANUAL
    # ===============================
    elif tipo == "anual":
        if not ano:
            ano = today.year
        else:
            ano = int(ano)

        dt_inicio = date(ano, 1, 1)
        dt_fim = date(ano, 12, 31)

    else:
        # nada selecionado → só exibir a tela
        return render_template("calendario.html", filtro_ativo=False)

    # ===========================================
    #  Recuperar transações do intervalo
    # ===========================================
    conn = conectar_bd()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT tipo, valor, categoria 
        FROM Transacoes 
        WHERE usuario_id = ? AND DATE(data) BETWEEN ? AND ?
    """, (session["user_id"], dt_inicio, dt_fim))

    transacoes = cursor.fetchall()

    # ===============================
    # Cálculo dos totais
    # ===============================
    total_rendas = sum(t["valor"] for t in transacoes if t["tipo"] == "renda")
    total_gastos = sum(t["valor"] for t in transacoes if t["tipo"] == "gasto")
    saldo = total_rendas - total_gastos

    # ===============================
    # Categorias e metas
    # ===============================
    cursor.execute("SELECT * FROM Configuracoes LIMIT 1")
    config = cursor.fetchone()

    metas = {
        "necessidades": total_rendas * (config["necessidades"] / 100),
        "lazer": total_rendas * (config["lazer"] / 100),
        "causas_sociais": total_rendas * (config["causas_sociais"] / 100),
        "reserva": total_rendas * (config["reserva"] / 100),
        "investimento": total_rendas * (config["investimento"] / 100),
    }

    categorias = ["necessidades", "lazer", "causas_sociais", "reserva", "investimento"]

    gastos = {cat: 0 for cat in categorias}

    for t in transacoes:

        # Ignorar rendas no cálculo de gastos
        if t["tipo"].lower() != "gasto":
            continue

        cat = t["categoria"]

        # Garantir que só categorias válidas sejam contadas
        if cat in gastos:
            gastos[cat] += t["valor"]

    comparacao = {
        cat: {
            "meta": metas[cat],
            "gasto": gastos[cat],
            "status": "dentro" if gastos[cat] <= metas[cat] else "excedido",
        }
        for cat in categorias
    }

    cores = ["#4e73df", "#1cc88a", "#36b9cc", "#f6c23e", "#e74a3b"]

    grafico_data = json.dumps({
        "categorias": [c.capitalize() for c in categorias],
        "gastos": [gastos[c] for c in categorias],
        "metas": [metas[c] for c in categorias],
        "cores": cores,
    })

    conn.close()

    return render_template(
        "calendario.html",
        filtro_ativo=True,
        total_rendas=total_rendas,
        total_gastos=total_gastos,
        saldo=saldo,
        comparacao=comparacao,
        grafico_data=grafico_data,
        dt_inicio=dt_inicio,
        dt_fim=dt_fim,
        tipo=tipo
    )

# =====================================================
# Execução do Aplicativo (LOCAL APENAS)
# =====================================================
if __name__ == '__main__':
    inicializar_bd()
    app.run(host='0.0.0.0', port=5000)
