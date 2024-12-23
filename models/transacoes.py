from config import db

class Transacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(10), nullable=False)  # 'renda' ou 'gasto'
    nome = db.Column(db.String(100), nullable=False)
    valor = db.Column(db.Float, nullable=False)
    periodo = db.Column(db.String(50), nullable=False)
    categoria = db.Column(db.String(50), nullable=True)  # Ex.: 'necessidades', 'lazer'
    data = db.Column(db.DateTime, default=db.func.current_timestamp())

    def __repr__(self):
        return f"<Transacao {self.nome} - {self.tipo} - {self.valor}>"
