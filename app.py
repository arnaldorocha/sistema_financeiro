from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file
from flask_apscheduler import APScheduler
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, timedelta
import sqlite3
import os
import json

app = Flask(__name__)
app.secret_key = os.urandom(24)

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

def inicializar_bd():
    conn = conectar_bd()
    if conn is None:
        return
    cursor = conn.cursor()
    # Adiciona as colunas necessárias (se já não existirem)
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

    # Cria as tabelas se não existirem
    cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        senha TEXT NOT NULL
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS Transacoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
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

    cursor.execute('''CREATE TABLE IF NOT EXISTS Avisos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        tipo TEXT NOT NULL,
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

@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']
    conn = sqlite3.connect('financeiro.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM usuarios WHERE username=?', (username,))
    user = cursor.fetchone()
    conn.close()
    if user and check_password_hash(user[2], password):
        session['user_id'] = user[0]
        return redirect(url_for('dashboard'))
    else:
        flash("Usuário ou Senha Inválidos", "error")
        return redirect(url_for('index'))

@app.route('/cadastro', methods=['GET','POST'])
def cadastro():
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
            cursor.execute("INSERT INTO usuarios (username, senha) VALUES (?, ?)", (username, hashed_password))
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
# Scheduler Tasks (Notificações e Resumo Diário)
# =====================================================

@scheduler.task('interval', id='notificar_transacoes', minutes=60)
def notificar_transacoes():
    conn = conectar_bd()
    if conn is None:
        return
    cursor = conn.cursor()
    data_atual = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("SELECT * FROM Transacoes WHERE data = ? AND notificado = 0", (data_atual,))
    transacoes = cursor.fetchall()
    for transacao in transacoes:
        mensagem = f"Hoje: {transacao['tipo'].capitalize()} '{transacao['nome']}' de R$ {transacao['valor']} vence hoje."
        cursor.execute("INSERT INTO Notificacoes (mensagem) VALUES (?)", (mensagem,))
        cursor.execute("UPDATE Transacoes SET notificado = 1 WHERE id = ?", (transacao['id'],))
    conn.commit()
    conn.close()

@scheduler.task('interval', id='notificar_transacoes_antecipadas', minutes=60)
def notificar_transacoes_antecipadas():
    conn = conectar_bd()
    if conn is None:
        return
    cursor = conn.cursor()
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    cursor.execute("SELECT * FROM Transacoes WHERE data = ? AND notificado_antecipado = 0", (tomorrow,))
    transacoes = cursor.fetchall()
    for transacao in transacoes:
        tipo = transacao['tipo'].strip().lower()
        nome = transacao['nome'].strip().lower()
        if (tipo == 'gasto' and 'investimento' in nome) or (tipo == 'renda'):
            mensagem = f"Amanhã: {transacao['tipo'].capitalize()} '{transacao['nome']}' de R$ {transacao['valor']}."
            cursor.execute("INSERT INTO Notificacoes (mensagem) VALUES (?)", (mensagem,))
            cursor.execute("UPDATE Transacoes SET notificado_antecipado = 1 WHERE id = ?", (transacao['id'],))
    conn.commit()
    conn.close()

@scheduler.task('cron', id='resumo_diario', hour=8)
def resumo_diario():
    conn = conectar_bd()
    if conn is None:
        return
    cursor = conn.cursor()
    data_atual = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("SELECT * FROM Transacoes WHERE data = ?", (data_atual,))
    transacoes = cursor.fetchall()
    if transacoes:
        resumo = "\n".join(f"{t['tipo'].capitalize()} - {t['nome']} - R$ {t['valor']}" for t in transacoes)
        mensagem = f"Resumo do dia {data_atual}:\n{resumo}"
        cursor.execute("INSERT INTO Notificacoes (mensagem) VALUES (?)", (mensagem,))
    conn.commit()
    conn.close()

# =====================================================
# Rotas de Sistema (Notificações, Calendário, Usuários)
# =====================================================

@app.route('/notificacoes')
def notificacoes():
    if 'user_id' not in session:
        flash("Você não está autenticado.", "error")
        return redirect(url_for('index'))
    conn = conectar_bd()
    if conn is None:
        flash("Erro ao conectar ao banco de dados", "danger")
        return redirect(url_for('index'))
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Notificacoes WHERE lida = 0 ORDER BY data_criacao DESC")
    notificacoes = cursor.fetchall()
    conn.close()
    return render_template('notificacoes.html', notificacoes=notificacoes)

@app.route('/marcar_como_lida/<int:notificacao_id>', methods=['POST'])
def marcar_como_lida(notificacao_id):
    if 'user_id' not in session:
        flash("Você não está autenticado.", "danger")
        return redirect(url_for('index'))
    conn = conectar_bd()
    if conn is None:
        flash("Erro ao conectar ao banco de dados", "danger")
        return redirect(url_for('index'))
    cursor = conn.cursor()
    cursor.execute("UPDATE Notificacoes SET lida = 1 WHERE id = ?", (notificacao_id,))
    conn.commit()
    conn.close()
    flash("Notificação marcada como lida.", "success")
    return redirect(url_for('notificacoes'))

@app.route('/calendario', methods=['GET'])
def calendario():
    if 'user_id' not in session:
        flash("Usuário não autenticado!", "danger")
        return redirect(url_for('login'))
    usuario_id = session['user_id']
    conn = conectar_bd()
    if conn is None:
        flash("Erro ao conectar ao banco de dados", "danger")
        return redirect(url_for('dashboard'))
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Avisos WHERE usuario_id = ? AND data >= ? ORDER BY data", 
                   (usuario_id, datetime.now().strftime('%Y-%m-%d')))
    avisos = cursor.fetchall()
    conn.close()
    return render_template('calendario.html', eventos=avisos)

@app.route('/gestao_usuarios')
def gestao_usuarios():
    try:
        conn = sqlite3.connect('financeiro.db')
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM usuarios")
        users = cursor.fetchall()
        conn.close()
        return render_template('gestao_usuarios.html', users=users)
    except Exception as e:
        return f"Erro ao carregar usuários: {str(e)}"

@app.route('/excluir_usuario/<int:user_id>', methods=['POST'])
def excluir_usuario(user_id):
    try:
        conn = sqlite3.connect('financeiro.db')
        cursor = conn.cursor()
        if 'user_id' in session and session['user_id'] == user_id:
            session.clear()
        cursor.execute("DELETE FROM usuarios WHERE id=?", (user_id,))
        conn.commit()
        conn.close()
        flash("Usuário excluído com sucesso!", "success")
        if 'user_id' not in session:
            return redirect(url_for('index'))
        else:
            return redirect(url_for('gestao_usuarios'))
    except Exception as e:
        flash(f"Erro ao excluir usuário: {str(e)}", "error")
        return redirect(url_for('gestao_usuarios'))

# =====================================================
# Rotas de Transações e Metas
# =====================================================

# Dashboard – exibe os dados do mês atual
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        flash("Você não está autenticado.", "error")
        return redirect(url_for('index'))
    try:
        # Intervalo do mês atual
        data_inicio = datetime.now().replace(day=1).strftime('%Y-%m-%d')
        data_fim = (datetime.now().replace(day=28) + timedelta(days=4)).replace(day=1).strftime('%Y-%m-%d')
        
        conn = conectar_bd()
        if conn is None:
            flash("Erro ao conectar ao banco de dados", "danger")
            return redirect(url_for('index'))
        cursor = conn.cursor()
        # Filtra transações do mês atual e com período 'mensal'
        cursor.execute("SELECT * FROM Transacoes WHERE periodo = 'mensal' AND data BETWEEN ? AND ? ORDER BY data DESC", (data_inicio, data_fim))
        transacoes = cursor.fetchall()
        cursor.execute("SELECT * FROM Configuracoes LIMIT 1")
        configuracoes = cursor.fetchone()
        cursor.execute("SELECT SUM(valor) FROM Transacoes WHERE LOWER(tipo) = 'renda' AND periodo = 'mensal' AND data BETWEEN ? AND ?", (data_inicio, data_fim))
        total_rendas = cursor.fetchone()[0] or 0
        cursor.execute("SELECT SUM(valor) FROM Transacoes WHERE LOWER(tipo) = 'gasto' AND periodo = 'mensal' AND data BETWEEN ? AND ?", (data_inicio, data_fim))
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
            cursor.execute("SELECT SUM(valor) FROM Transacoes WHERE LOWER(categoria) = ? AND LOWER(tipo) = 'gasto' AND periodo = 'mensal' AND data BETWEEN ? AND ?", (cat.lower(), data_inicio, data_fim))
            gastos[cat] = cursor.fetchone()[0] or 0
        comparacao = {cat: {
                "meta": metas[cat],
                "gasto": gastos[cat],
                "status": "dentro" if gastos[cat] <= metas[cat] else "excedido"
            } for cat in categorias}
        # Dados para o gráfico
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

# =====================================================
# Rota para Visualizar/Editar/Inserir Transações com Filtro
# =====================================================

@app.route('/transacoes', methods=['GET'])
def transacoes_view():
    if 'user_id' not in session:
        flash("Você não está autenticado.", "error")
        return redirect(url_for('index'))
    # Filtra por período e pesquisa (query string)
    periodo = request.args.get('periodo')  # valores esperados: 'diario', 'semanal', 'mensal', 'anual'
    pesquisa = request.args.get('pesquisa', '').lower()
    conn = conectar_bd()
    if conn is None:
        flash("Erro ao conectar ao banco de dados", "danger")
        return redirect(url_for('dashboard'))
    cursor = conn.cursor()
    if periodo:
        cursor.execute("SELECT * FROM Transacoes WHERE periodo = ? ORDER BY data DESC", (periodo,))
    else:
        cursor.execute("SELECT * FROM Transacoes ORDER BY data DESC")
    transacoes = cursor.fetchall()
    conn.close()
    # Se houver termo de pesquisa, filtra os registros localmente
    if pesquisa:
        transacoes = [t for t in transacoes if pesquisa in t['nome'].lower()]
    return render_template('transacoes.html', transacoes=transacoes, periodo=periodo, pesquisa=pesquisa)

# =====================================================
# Rotas para Inserir, Editar e Excluir Transações
# =====================================================

@app.route('/adicionar_transacao', methods=['GET', 'POST'])
def adicionar_transacao():
    if request.method == 'POST':
        tipo = request.form['tipo'].strip().lower()
        nome = request.form['nome']
        valor = float(request.form['valor'])
        periodo = request.form['periodo']
        data = request.form['data']
        # Se for investimento, trata-o como gasto inicialmente
        if tipo == 'investimento':
            tipo = 'gasto'
        categoria = request.form['categoria'] if tipo == 'gasto' else 'necessidades'
        conn = conectar_bd()
        if conn is None:
            flash("Erro ao conectar ao banco de dados", "danger")
            return redirect(url_for('index'))
        cursor = conn.cursor()
        cursor.execute("INSERT INTO Transacoes (tipo, nome, valor, periodo, categoria, data) VALUES (?, ?, ?, ?, ?, ?)",
                       (tipo, nome, valor, periodo, categoria, data))
        conn.commit()
        if data == datetime.now().strftime('%Y-%m-%d'):
            notificar_transacoes()
        conn.close()
        flash("Transação adicionada com sucesso!", "success")
        return redirect(url_for('transacoes_view'))
    return render_template('adicionar_transacao.html')

@app.route('/editar_transacao/<int:id>', methods=['GET', 'POST'])
def editar_transacao(id):
    conn = conectar_bd()
    if conn is None:
        flash("Erro ao conectar ao banco de dados", "danger")
        return redirect(url_for('index'))
    cursor = conn.cursor()
    if request.method == 'POST':
        tipo = request.form['tipo'].strip().lower()
        nome = request.form['nome']
        valor = float(request.form['valor'])
        periodo = request.form['periodo']
        data = request.form['data']
        if tipo == 'investimento':
            tipo = 'gasto'
        categoria = request.form['categoria'] if tipo == 'gasto' else 'necessidades'
        cursor.execute("UPDATE Transacoes SET tipo = ?, nome = ?, valor = ?, periodo = ?, categoria = ?, data = ? WHERE id = ?",
                       (tipo, nome, valor, periodo, categoria, data, id))
        conn.commit()
        if data == datetime.now().strftime('%Y-%m-%d'):
            notificar_transacoes()
        conn.close()
        flash("Transação atualizada com sucesso!", "success")
        return redirect(url_for('transacoes_view'))
    cursor.execute("SELECT * FROM Transacoes WHERE id = ?", (id,))
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
    cursor.execute("DELETE FROM Transacoes WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    flash("Transação excluída com sucesso!", "success")
    return redirect(url_for('transacoes_view'))

# =====================================================
# Rota para Editar Metas
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
# Rotas para Contas e Conselhos Financeiros
# =====================================================

@app.route('/contas')
def contas():
    if 'user_id' not in session:
        flash("Você não está autenticado.", "error")
        return redirect(url_for('index'))
    conn = conectar_bd()
    if conn is None:
        flash("Erro ao conectar ao banco de dados", "danger")
        return redirect(url_for('dashboard'))
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Avisos ORDER BY data ASC")
    avisos = cursor.fetchall()
    conn.close()
    return render_template('contas.html', avisos=avisos)

@app.route('/conselhos')
def conselhos():
    orientacoes = {
        "investimento": "Investimento ou poupança: garanta uma fonte extra de renda. Não gaste além da meta.",
        "reserva": "Uma reserva de emergência é crucial para enfrentar imprevistos. Não utilize para despesas correntes.",
        "causas_sociais": "Doações são uma ótima forma de ajudar. Destine esse valor com consciência.",
        "lazer": "Lazer é importante, mas não ultrapasse sua meta para não comprometer outras áreas.",
        "necessidades": "Gastos essenciais devem ser otimizados: busque eficiência e evite excessos."
    }
    return render_template('conselhos.html', orientacoes=orientacoes)

# =====================================================
# Execução do Aplicativo
# =====================================================
if __name__ == '__main__':
    inicializar_bd()
    app.run(debug=True)
