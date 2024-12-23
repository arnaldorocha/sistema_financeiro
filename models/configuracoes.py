from config import db

class Configuracao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    poupanca = db.Column(db.Float, default=10.0)
    reserva = db.Column(db.Float, default=10.0)
    causas_sociais = db.Column(db.Float, default=10.0)
    lazer = db.Column(db.Float, default=20.0)
    necessidades = db.Column(db.Float, default=50.0)

    def __repr__(self):
        return f"<Configuracao Poupança: {self.poupanca}% Necessidades: {self.necessidades}%>"
