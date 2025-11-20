// Configurações dos gráficos
const ctxGastos = document.getElementById('graficoGastos').getContext('2d');
new Chart(ctxGastos, {
    type: 'pie',
    data: {
        labels: ['Necessidades', 'Lazer', 'Poupança', 'Reserva', 'Causas Sociais'],
        datasets: [{
            data: [{{ gastos.necessidades }}, {{ gastos.lazer }}, {{ gastos.poupanca }}, {{ gastos.reserva }}, {{ gastos.causas_sociais }}],
            backgroundColor: ['#007bff', '#ffc107', '#28a745', '#17a2b8', '#6c757d'],
        }]
    }
});

// Calendário
document.addEventListener('DOMContentLoaded', function () {
    const calendarEl = document.getElementById('calendar');
    const calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'dayGridMonth',
        events: '/api/calendar_events', // URL que retorna eventos no formato JSON
    });
    calendar.render();
});


/* # Este código é propriedade de Arnaldo Rocha Filho
   # Direitos Reservados © 2024
*/
