from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_apscheduler import APScheduler
from werkzeug.security import check_password_hash, generate_password_hash
from flask import send_file
from datetime import datetime
import sqlite3
import os
import csv

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Configuração do APScheduler
scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

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
    
    # Verifica e adiciona colunas necessárias
    try:
        cursor.execute("ALTER TABLE Transacoes ADD COLUMN categoria TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE Transacoes ADD COLUMN notificado INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # Cria tabelas se não existirem
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
        notificado INTEGER DEFAULT 0
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS Configuracoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        poupanca REAL DEFAULT 10.0,
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
        tipo TEXT NOT NULL, -- 'pagar' ou 'receber'
        nome TEXT NOT NULL,
        valor REAL NOT NULL,
        data DATE NOT NULL,
        status TEXT DEFAULT 'pendente'
    );''')



    cursor.execute('''INSERT INTO Configuracoes (poupanca, reserva, causas_sociais, lazer, necessidades)
    SELECT 10, 10, 10, 20, 50 WHERE NOT EXISTS (SELECT 1 FROM Configuracoes)''')

    conn.commit()
    conn.close()
    

@app.route('/')
def index():
    return render_template('login.html')
    
@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']

    # Conecta ao banco de dados SQLite
    conn = sqlite3.connect('financeiro.db')
    cursor = conn.cursor()

    # Obtém o hash da senha do banco de dados
    cursor.execute('SELECT * FROM usuarios WHERE username=?', (username,))
    user = cursor.fetchone()

    # Fecha a conexão
    conn.close()

    if user and check_password_hash(user[2], password):  # Aqui está a alteração
        # Lógica de autenticação bem-sucedida, pode ser expandida conforme necessário
        session['user_id'] = user[0]
        return redirect(url_for('dashboard'))
    else:
        # Lógica de autenticação falhou, redireciona de volta para a página de login
        flash('error', 'Usuário ou Senha Inválidos')
        return redirect(url_for('index'))

@app.route('/cadastro', methods=['GET','POST'])
def cadastro():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirmPassword']

        if password != confirm_password:
            flash('error', 'As senhas não coincidem. Por favor, insira senhas iguais.')
            return redirect(url_for('cadastro'))

        hashed_password = generate_password_hash(password)

        try:
            conn = sqlite3.connect('financeiro.db')
            cursor = conn.cursor()

            cursor.execute("SELECT id FROM usuarios WHERE username = ?", (username,))
            existing_user = cursor.fetchone()

            if existing_user:
                flash('error', 'Este usuário já existe. Por favor, escolha um nome de usuário diferente.')
                return redirect(url_for('cadastro'))

            cursor.execute("INSERT INTO usuarios (username, senha) VALUES (?, ?)", (username, hashed_password))
            conn.commit()

            flash('success', 'Cadastro realizado com sucesso! Faça o login para acessar sua conta.')
            return redirect(url_for('index'))

        except Exception as e:
            flash('error', f"Erro ao cadastrar usuário: {str(e)}")
            return redirect(url_for('cadastro'))

        finally:
            conn.close()

    return render_template('cadastro.html')


@scheduler.task('interval', id='notificar_transacoes', minutes=60)
def notificar_transacoes():
    conn = conectar_bd()
    cursor = conn.cursor()
    data_atual = datetime.now().strftime('%Y-%m-%d')

    # Verifica transações não notificadas
    cursor.execute('''SELECT * FROM Transacoes 
                      WHERE data = ? AND notificado = 0''', (data_atual,))
    transacoes = cursor.fetchall()

    for transacao in transacoes:
        mensagem = f"Lembrete: {transacao['tipo'].capitalize()} '{transacao['nome']}' de R${transacao['valor']} vence hoje."
        cursor.execute("INSERT INTO Notificacoes (mensagem) VALUES (?)", (mensagem,))
        cursor.execute("UPDATE Transacoes SET notificado = 1 WHERE id = ?", (transacao['id'],))

    conn.commit()
    conn.close()

@scheduler.task('cron', id='resumo_diario', hour=8)
def resumo_diario():
    conn = conectar_bd()
    cursor = conn.cursor()
    data_atual = datetime.now().strftime('%Y-%m-%d')

    cursor.execute('''SELECT * FROM Transacoes WHERE data = ?''', (data_atual,))
    transacoes = cursor.fetchall()

    if transacoes:
        resumo = "\n".join(
            f"{transacao['tipo'].capitalize()} - {transacao['nome']} - R${transacao['valor']}" 
            for transacao in transacoes
        )
        mensagem = f"Resumo do dia {data_atual}:\n{resumo}"
        cursor.execute("INSERT INTO Notificacoes (mensagem) VALUES (?)", (mensagem,))

    conn.commit()
    conn.close()

@app.route('/notificacoes')
def notificacoes():
    if 'user_id' not in session:
        flash('Você não está autenticado.','error')
        return redirect(url_for('index'))

    conn = conectar_bd()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM Notificacoes WHERE lida = 0 ORDER BY data_criacao DESC')
    notificacoes = cursor.fetchall()

    conn.close()
    return render_template('notificacoes.html', notificacoes=notificacoes)

@app.route('/marcar_como_lida/<int:notificacao_id>', methods=['POST'])
def marcar_como_lida(notificacao_id):
    if 'user_id' not in session:
        flash('Você não está autenticado.', 'danger')
        return redirect(url_for('index'))

    conn = conectar_bd()
    cursor = conn.cursor()
    cursor.execute('''UPDATE Notificacoes SET lida = 1 WHERE id = ?''', (notificacao_id,))
    conn.commit()
    conn.close()

    flash('Notificação marcada como lida.', 'success')
    return redirect(url_for('notificacoes'))

@app.route('/calendario', methods=['GET'])
def calendario():
    if 'usuario_id' not in session:
        flash("Usuário não autenticado!", "danger")
        return redirect(url_for('login'))
    
    usuario_id = session['usuario_id']  # Obtém o usuário logado
    conn = conectar_bd()
    cursor = conn.cursor()
    
    # Consulta para pegar avisos futuros
    cursor.execute("SELECT * FROM Avisos WHERE usuario_id = ? AND data >= ? ORDER BY data", 
                   (usuario_id, datetime.now().strftime('%Y-%m-%d')))
    avisos = cursor.fetchall()
    
    conn.close()

    # Organiza os dados no formato que o FullCalendar espera (data, título, etc.)
    eventos = []
    for aviso in avisos:
        evento = {
            'title': aviso['nome'],
            'start': aviso['data'],  # Certifique-se de que a data está no formato correto
            'description': f'{aviso["tipo"]} de R${aviso["valor"]}',
            'status': aviso['status']
        }
        eventos.append(evento)

    # Retorna os dados para o template do calendário
    return render_template('calendario.html', eventos=eventos)

@app.route('/gestao_usuarios')
def gestao_usuarios():
    try:
        # Conectar ao banco de dados SQLite
        conn = sqlite3.connect('financeiro.db')
        cursor = conn.cursor()

        # Consulta para obter todos os usuários
        cursor.execute('SELECT * FROM usuarios')
        users = cursor.fetchall()

        # Fechar a conexão com o banco de dados
        conn.close()

        return render_template('gestao_usuarios.html', users=users)

    except Exception as e:
        # Trate a exceção conforme necessário
        return f"Erro ao carregar usuários: {str(e)}"

@app.route('/excluir_usuario/<int:user_id>', methods=['POST'])
def excluir_usuario(user_id):
    try:
        # Conectar ao banco de dados SQLite
        conn = sqlite3.connect('financeiro.db')
        cursor = conn.cursor()

        # Verificar se o usuário está excluindo a própria conta
        if 'user_id' in session and session['user_id'] == user_id:
            # Limpar a sessão (logout) se o usuário estiver excluindo sua própria conta
            session.clear()

        # Excluir o usuário com base no ID
        cursor.execute('DELETE FROM usuarios WHERE id=?', (user_id,))

        # Commit e fechar a conexão
        conn.commit()
        conn.close()

        flash('success', 'Usuário excluído com sucesso!')

        # Redirecionar para a página de login se o usuário excluiu sua própria conta
        if 'user_id' not in session:
            return redirect(url_for('index'))
        else:
            return redirect(url_for('gestao_usuarios'))

    except Exception as e:
        flash('error', f"Erro ao excluir usuário: {str(e)}")
        return redirect(url_for('gestao_usuarios'))



@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        flash('error', 'Você não está autenticado.' )
        return redirect(url_for('index'))
    try:
        conn = conectar_bd()
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM Transacoes')
        transacoes = cursor.fetchall()

        cursor.execute('SELECT * FROM Configuracoes LIMIT 1')
        configuracoes = cursor.fetchone()

        cursor.execute("SELECT SUM(valor) FROM Transacoes WHERE tipo = 'renda'")
        total_rendas = cursor.fetchone()[0] or 0

        cursor.execute("SELECT SUM(valor) FROM Transacoes WHERE tipo = 'gasto'")
        total_gastos = cursor.fetchone()[0] or 0
        saldo = total_rendas - total_gastos

        alerta_saldo = "Seu saldo está negativo. Recomenda-se aumentar a renda ou reduzir os gastos." if saldo < 0 else ""

        metas = {
            'poupanca': total_rendas * (configuracoes['poupanca'] / 100),
            'reserva': total_rendas * (configuracoes['reserva'] / 100),
            'causas_sociais': total_rendas * (configuracoes['causas_sociais'] / 100),
            'lazer': total_rendas * (configuracoes['lazer'] / 100),
            'necessidades': total_rendas * (configuracoes['necessidades'] / 100),
        }

        orientacao_gastos = {
            'poupanca': "Poupança é importante para garantir um futuro tranquilo. Tente não gastar mais do que a meta.",
            'reserva': "Uma reserva de emergência é crucial. Não use este valor para despesas do dia a dia.",
            'causas_sociais': "Doações são uma ótima maneira de ajudar. Se você tem condições, destine esse valor com consciência.",
            'lazer': "Lazer é importante, mas procure não ultrapassar sua meta para não comprometer outras necessidades.",
            'necessidades': "Esses gastos são essenciais, mas sempre busque eficiência e evite excessos.",
        }

        categorias = ['necessidades', 'lazer', 'causas_sociais', 'reserva', 'poupanca']
        gastos = {}
        for categoria in categorias:
            cursor.execute(f"""
                SELECT SUM(valor) 
                FROM Transacoes 
                WHERE categoria = ? AND tipo = 'gasto'
            """, (categoria,))
            gastos[categoria] = cursor.fetchone()[0] or 0

        comparacao = {
            categoria: {
                "meta": metas[categoria],
                "gasto": gastos[categoria],
                "status": "dentro" if gastos[categoria] <= metas[categoria] else "excedido"
            }
            for categoria in categorias
        }

        return render_template(
            'dashboard.html',
            saldo=round(saldo, 2),
            metas={k: round(v, 2) for k, v in metas.items()},
            alerta_saldo=alerta_saldo,
            orientacao_gastos=orientacao_gastos,
            total_rendas=round(total_rendas, 2),
            transacoes=transacoes,
            gastos={k: round(v, 2) for k, v in gastos.items()},
            comparacao=comparacao,
        )

    except Exception as e:
        flash('error', f"Erro ao carregar transações: {str(e)}")
        return redirect(url_for('index'))


@app.route('/adicionar_transacao', methods=['GET', 'POST'])
def adicionar_transacao():
    if request.method == 'POST':
        tipo = request.form['tipo']
        nome = request.form['nome']
        valor = float(request.form['valor'])
        periodo = request.form['periodo']
        data = request.form['data']
        
        # Se for renda, a categoria será "necessidades" por padrão
        categoria = request.form['categoria'] if tipo == 'gasto' else 'necessidades'

        conn = conectar_bd()
        if conn is None:
            flash("Erro ao conectar ao banco de dados", "danger")
            return redirect(url_for('index'))

        cursor = conn.cursor()
        cursor.execute('''INSERT INTO Transacoes (tipo, nome, valor, periodo, categoria, data) 
                          VALUES (?, ?, ?, ?, ?, ?)''', 
                       (tipo, nome, valor, periodo, categoria, data))
        conn.commit()
        
        # Verificar e processar notificação
        if data == datetime.now().strftime('%Y-%m-%d'):
            notificar_transacoes()

        conn.close()
        flash("Transação adicionada com sucesso!", "success")
        return redirect(url_for('dashboard'))

    return render_template('adicionar_transacao.html')


@app.route('/editar_transacao/<int:id>', methods=['GET', 'POST'])
def editar_transacao(id):
    conn = conectar_bd()
    if conn is None:
        flash("Erro ao conectar ao banco de dados", "danger")
        return redirect(url_for('index'))

    cursor = conn.cursor()

    if request.method == 'POST':
        tipo = request.form['tipo']
        nome = request.form['nome']
        valor = float(request.form['valor'])
        periodo = request.form['periodo']
        data = request.form['data']
        
        # Se for renda, a categoria será "necessidades" por padrão
        categoria = request.form['categoria'] if tipo == 'gasto' else 'necessidades'

        cursor.execute('''UPDATE Transacoes
                          SET tipo = ?, nome = ?, valor = ?, periodo = ?, categoria = ?, data = ?
                          WHERE id = ?''', 
                       (tipo, nome, valor, periodo, categoria, data, id))
        conn.commit()
        
        # Verificar e processar notificação
        if data == datetime.now().strftime('%Y-%m-%d'):
            notificar_transacoes()

        conn.close()
        flash("Transação atualizada com sucesso!", "success")
        return redirect(url_for('dashboard'))

    cursor.execute('SELECT * FROM Transacoes WHERE id = ?', (id,))
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

    cursor.execute('DELETE FROM Transacoes WHERE id = ?', (id,))
    conn.commit()
    conn.close()

    flash("Transação excluída com sucesso!", "success")
    return redirect(url_for('dashboard'))


@app.route('/editar_metas', methods=['GET', 'POST'])
def editar_metas():
    conn = conectar_bd()
    if conn is None:
        flash("Erro ao conectar ao banco de dados", "danger")
        return redirect(url_for('index'))

    cursor = conn.cursor()

    # Buscar metas financeiras
    cursor.execute('SELECT * FROM Configuracoes LIMIT 1')
    configuracoes = cursor.fetchone()

    if request.method == 'POST':
        # Atualizar metas financeiras
        poupanca = float(request.form['poupanca'])
        reserva = float(request.form['reserva'])
        causas_sociais = float(request.form['causas_sociais'])
        lazer = float(request.form['lazer'])
        necessidades = float(request.form['necessidades'])
    
        cursor.execute('''UPDATE Configuracoes 
                          SET poupanca = ?, reserva = ?, causas_sociais = ?, lazer = ?, necessidades = ? 
                          WHERE id = 1''',
                          (poupanca, reserva, causas_sociais, lazer, necessidades))
        conn.commit()
        conn.close()

        flash("Metas atualizadas com sucesso!", "success")
        return redirect(url_for('dashboard'))

    conn.close()
    return render_template('editar_metas.html', configuracoes=configuracoes)


# Inicializar banco de dados
if __name__ == '__main__':
    inicializar_bd()
    app.run(debug=True)
    
# Este código é propriedade de Arnaldo Rocha Filho
# Direitos Reservados © 2024
