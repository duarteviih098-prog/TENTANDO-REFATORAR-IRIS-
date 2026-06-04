/**
 * iris-live-search.js
 * Busca em tempo real para todos os modulos do IRIS.
 *
 * Como usar nos templates:
 *   <input class="form-control iris-live-search"
 *          data-module="os"
 *          data-target="#results-container"
 *          data-render="os"
 *          placeholder="Buscar por descricao, sistema...">
 *
 * Atributos:
 *   data-module  : nome do modulo (os, controle, pagamentos, combustivel, custos, os_ativos)
 *   data-target  : seletor CSS do elemento que recebe os resultados
 *   data-render  : qual template de render usar (igual ao module normalmente)
 *   data-form    : (opcional) seletor do form de filtro para submit junto
 */

(function() {
  'use strict';

  var DEBOUNCE_MS = 400;

  // Templates de render para cada modulo
  var renderers = {
    os: function(row) {
      var status = (row.status || 'Aberta');
      var chip = status.toLowerCase() === 'finalizada' ? 'status-ok' :
                 status.toLowerCase() === 'em andamento' ? 'status-info' : 'status-warn';
      return '<div class="live-result-item" data-id="' + row.id + '">' +
        '<div class="live-result-main">' +
          '<span class="live-result-title">' + esc(row.sistema || '') + ' — ' + esc(row.equipamento || '') + '</span>' +
          '<span class="status-chip ' + chip + '">' + esc(status) + '</span>' +
        '</div>' +
        '<div class="live-result-sub">' + esc(row.descricao || '') + '</div>' +
        '<div class="live-result-meta">' + esc(row.data || '') + (row.responsavel ? ' · ' + esc(row.responsavel) : '') + '</div>' +
      '</div>';
    },
    controle: function(row) {
      return '<div class="live-result-item" data-id="' + row.id + '">' +
        '<div class="live-result-main">' +
          '<span class="live-result-title">' + esc(row.equipamento || row.nome || '') + '</span>' +
          '<span class="live-result-badge">' + esc(row.localizacao || '') + '</span>' +
        '</div>' +
        '<div class="live-result-sub">' + esc(row.modelo || '') + (row.fornecedor ? ' · ' + esc(row.fornecedor) : '') + '</div>' +
        '<div class="live-result-meta">' + esc(row.obs || row.observacoes || '') + '</div>' +
      '</div>';
    },
    pagamentos: function(row) {
      var pago = (row.status || '').toLowerCase() === 'sim';
      return '<div class="live-result-item" data-id="' + row.id + '">' +
        '<div class="live-result-main">' +
          '<span class="live-result-title">' + esc(row.fornecedor || '') + '</span>' +
          '<span class="status-chip ' + (pago ? 'status-ok' : 'status-warn') + '">' + (pago ? 'Pago' : 'Pendente') + '</span>' +
        '</div>' +
        '<div class="live-result-sub">' + esc(row.descricao_servico || '') + '</div>' +
        '<div class="live-result-meta">' + esc(row.pagamento_mes || '') + (row.valor ? ' · R$ ' + esc(row.valor) : '') + '</div>' +
      '</div>';
    },
    combustivel: function(row) {
      return '<div class="live-result-item" data-id="' + row.id + '">' +
        '<div class="live-result-main">' +
          '<span class="live-result-title">' + esc(row.motorista || '') + '</span>' +
          '<span class="live-result-badge">' + esc(row.placa || '') + '</span>' +
        '</div>' +
        '<div class="live-result-sub">' + esc(row.modelo_veiculo || '') + ' · ' + esc(row.km || '') + ' km</div>' +
        '<div class="live-result-meta">' + esc(row.data || '') + (row.custo ? ' · R$ ' + esc(row.custo) : '') + '</div>' +
      '</div>';
    },
    custos: function(row) {
      return '<div class="live-result-item" data-id="' + row.id + '">' +
        '<div class="live-result-main">' +
          '<span class="live-result-title">' + esc(row.sistema || '') + ' — ' + esc(row.equipamento || '') + '</span>' +
        '</div>' +
        '<div class="live-result-sub">' + esc(row.descricao_os || '') + '</div>' +
        '<div class="live-result-meta">O.S. ' + esc(row.nr_os || '') + ' · ' + esc(row.mes || '') + '</div>' +
      '</div>';
    },
    os_ativos: function(row) {
      return '<div class="live-result-item" data-id="' + row.id + '">' +
        '<div class="live-result-main">' +
          '<span class="live-result-title">' + esc(row.nome || '') + '</span>' +
          '<span class="live-result-badge">' + esc(row.tipo || '') + '</span>' +
        '</div>' +
        '<div class="live-result-sub">' + esc(row.sistema || '') + (row.local ? ' · ' + esc(row.local) : '') + '</div>' +
        '<div class="live-result-meta">' + esc(row.status || '') + '</div>' +
      '</div>';
    },
  };

  function esc(str) {
    return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function debounce(fn, ms) {
    var t;
    return function() {
      var args = arguments;
      clearTimeout(t);
      t = setTimeout(function() { fn.apply(null, args); }, ms);
    };
  }

  function injectStyles() {
    if (document.getElementById('iris-live-search-styles')) return;
    var style = document.createElement('style');
    style.id = 'iris-live-search-styles';
    style.textContent = [
      '.live-search-wrapper{position:relative}',
      '.live-search-dropdown{position:absolute;top:calc(100% + 4px);left:0;right:0;z-index:9999;',
        'background:var(--surface2,#fff);border:1px solid var(--line,#e2e8f0);border-radius:16px;',
        'box-shadow:0 8px 32px rgba(20,40,70,.13);max-height:420px;overflow-y:auto;display:none}',
      '.live-search-dropdown.open{display:block}',
      '.live-result-item{padding:12px 16px;border-bottom:1px solid var(--line,#e2e8f0);cursor:pointer;transition:background .12s}',
      '.live-result-item:last-child{border-bottom:none}',
      '.live-result-item:hover{background:var(--surface,#f7f9fc)}',
      '.live-result-main{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:3px}',
      '.live-result-title{font-weight:800;font-size:.93rem}',
      '.live-result-badge{font-size:.75rem;font-weight:700;background:var(--surface,#f1f5f9);',
        'border-radius:999px;padding:2px 8px;color:var(--muted,#64748b)}',
      '.live-result-sub{font-size:.84rem;color:var(--muted,#64748b);margin-bottom:2px;',
        'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}',
      '.live-result-meta{font-size:.78rem;color:var(--muted,#94a3b8)}',
      '.live-search-empty{padding:16px;text-align:center;color:var(--muted,#94a3b8);font-size:.88rem}',
      '.live-search-loading{padding:12px 16px;text-align:center;color:var(--muted,#94a3b8);font-size:.85rem}',
      '.status-info{background:rgba(59,130,246,.14);color:#2563eb}',
      '.status-warn{background:rgba(234,179,8,.14);color:#b45309}',
    ].join('');
    document.head.appendChild(style);
  }

  function setupLiveSearch(input) {
    var module = input.getAttribute('data-module');
    var targetSel = input.getAttribute('data-target');
    var renderKey = input.getAttribute('data-render') || module;
    var renderer = renderers[renderKey];

    if (!module) return;

    injectStyles();

    // Wrap input in relative container
    var wrapper = input.parentNode;
    if (!wrapper.classList.contains('live-search-wrapper')) {
      var w = document.createElement('div');
      w.className = 'live-search-wrapper';
      input.parentNode.insertBefore(w, input);
      w.appendChild(input);
      wrapper = w;
    }

    var dropdown = document.createElement('div');
    dropdown.className = 'live-search-dropdown';
    wrapper.appendChild(dropdown);

    var currentXhr = null;
    var lastQ = null;

    function doSearch(q) {
      if (q === lastQ) return;
      lastQ = q;

      if (!q || q.length < 2) {
        dropdown.classList.remove('open');
        dropdown.innerHTML = '';
        // Se tem target, nao faz nada — deixa a lista original
        return;
      }

      dropdown.innerHTML = '<div class="live-search-loading">Buscando...</div>';
      dropdown.classList.add('open');

      if (currentXhr) currentXhr.abort();
      var xhr = new XMLHttpRequest();
      currentXhr = xhr;
      xhr.open('GET', '/api/search?module=' + encodeURIComponent(module) + '&q=' + encodeURIComponent(q) + '&limit=30');
      xhr.onload = function() {
        if (xhr.status !== 200) {
          dropdown.innerHTML = '<div class="live-search-empty">Erro na busca.</div>';
          return;
        }
        var data = JSON.parse(xhr.responseText);
        var rows = data.rows || [];
        if (!rows.length) {
          dropdown.innerHTML = '<div class="live-search-empty">Nenhum resultado para "' + esc(q) + '".</div>';
          return;
        }
        var html = rows.map(function(row) {
          return renderer ? renderer(row) : defaultRender(row);
        }).join('');
        dropdown.innerHTML = html;

        // Click em resultado
        dropdown.querySelectorAll('.live-result-item').forEach(function(item) {
          item.addEventListener('click', function() {
            var id = item.getAttribute('data-id');
            dropdown.classList.remove('open');
            // Tenta abrir o modal de edicao se existir
            var editBtn = document.querySelector('[data-id="' + id + '"][data-bs-toggle="modal"], [data-id="' + id + '"].btn-edit, [data-record-id="' + id + '"]');
            if (editBtn) {
              editBtn.click();
            } else {
              // Fallback: preenche o campo de busca do form e submete
              var formQ = document.querySelector('input[name="q"]');
              if (formQ) { formQ.value = item.querySelector('.live-result-sub') ? item.querySelector('.live-result-sub').textContent : q; }
              var form = document.querySelector('form[method="get"]');
              if (form) form.submit();
            }
          });
        });
      };
      xhr.onerror = function() {
        dropdown.innerHTML = '<div class="live-search-empty">Erro de conexao.</div>';
      };
      xhr.send();
    }

    function defaultRender(row) {
      var keys = Object.keys(row).filter(function(k) { return k !== 'id' && row[k]; });
      return '<div class="live-result-item" data-id="' + row.id + '">' +
        '<div class="live-result-main"><span class="live-result-title">ID ' + row.id + '</span></div>' +
        '<div class="live-result-sub">' + keys.slice(0,3).map(function(k){ return esc(row[k]); }).join(' · ') + '</div>' +
      '</div>';
    }

    var debouncedSearch = debounce(function() { doSearch(input.value.trim()); }, DEBOUNCE_MS);
    input.addEventListener('input', debouncedSearch);

    // Fecha dropdown ao clicar fora
    document.addEventListener('click', function(e) {
      if (!wrapper.contains(e.target)) {
        dropdown.classList.remove('open');
      }
    });

    // ESC fecha
    input.addEventListener('keydown', function(e) {
      if (e.key === 'Escape') dropdown.classList.remove('open');
    });
  }

  // Inicializa todos os inputs marcados
  function init() {
    document.querySelectorAll('.iris-live-search').forEach(setupLiveSearch);

    // Tambem hookeia inputs de busca genericos (name="q") em forms de modulos
    // quando tiverem data-module no form pai
    document.querySelectorAll('form[data-module] input[name="q"]').forEach(function(input) {
      if (!input.classList.contains('iris-live-search')) {
        input.setAttribute('data-module', input.closest('form').getAttribute('data-module'));
        input.setAttribute('data-render', input.closest('form').getAttribute('data-module'));
        input.classList.add('iris-live-search');
        setupLiveSearch(input);
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
