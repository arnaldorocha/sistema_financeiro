document.addEventListener('DOMContentLoaded', () => {
    carregarRelatorio();

    // Gráfico
    fetch('/api/transacoes')
        .then(res => res.json())
        .then(transacoes => {
            const rendas = transacoes.filter(t => t.tipo === 'renda');
            const gastos = transacoes.filter(t => t.tipo === 'gasto');

            const labels = ['Diário', 'Semanal', 'Mensal', 'Anual'];
            const valoresRenda = [0, 0, 0, 0];
            const valoresGasto = [0, 0, 0, 0];

            rendas.forEach(r => {
                const idx = labels.indexOf(r.periodo);
                valoresRenda[idx] += r.valor;
            });

            gastos.forEach(g => {
                const idx = labels.indexOf(g.periodo);
                valoresGasto[idx] += g.valor;
            });

            const ctx = document.getElementById('grafico-rendas-gastos').getContext('2d');
            new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [
                        {
                            label: 'Rendas',
                            data: valoresRenda,
                            backgroundColor: 'rgba(75, 192, 192, 0.2)',
                            borderColor: 'rgba(75, 192, 192, 1)',
                            borderWidth: 1
                        },
                        {
                            label: 'Gastos',
                            data: valoresGasto,
                            backgroundColor: 'rgba(255, 99, 132, 0.2)',
                            borderColor: 'rgba(255, 99, 132, 1)',
                            borderWidth: 1
                        }
                    ]
                },
                options: {
                    scales: {
                        y: {
                            beginAtZero: true
                        }
                    }
                }
            });
        });
});

function carregarRelatorio() {
    fetch('/api/relatorio')
        .then(res => res.json())
        .then(data => {
            document.getElementById('saldo').innerText = `Saldo Mensal: R$ ${data.saldo.toFixed(2)}`;
            
            const metas = data.metas;
            const metasElement = document.getElementById('metas');
            metasElement.innerHTML = `
                <li>Poupança: R$ ${metas.investimento.toFixed(2)}</li>
                <li>Reserva: R$ ${metas.reserva.toFixed(2)}</li>
                <li>Causas Sociais: R$ ${metas.causas_sociais.toFixed(2)}</li>
                <li>Lazer: R$ ${metas.lazer.toFixed(2)}</li>
                <li>Necessidades: R$ ${metas.necessidades.toFixed(2)}</li>
            `;
        });
}


function toggleCategoria() {
    const tipo = document.getElementById('tipo').value;
    const categoriaField = document.getElementById('categoriaField');
    if (tipo === 'renda') {
        categoriaField.style.display = 'none';  // Ocultar categoria
    } else {
        categoriaField.style.display = 'block'; // Mostrar categoria
    }
}


/* # Este código é propriedade de Arnaldo Rocha Filho
   # Direitos Reservados © 2024
*/
