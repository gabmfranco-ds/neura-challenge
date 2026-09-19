// Tela do Agent Marketplace de imóveis.
//
// Duas regras que não mudam:
//   1. todo dado dinâmico entra por textContent. Nada de innerHTML.
//   2. reprise nunca se passa por ao vivo: a faixa roxa fica no alto o tempo
//      todo enquanto o modo for reprise.

const $ = (id) => document.getElementById(id);

const ESTADO = {
  rodadaId: null,
  since: 0,
  modo: "ao-vivo",      // "ao-vivo" ou "reprise"
  sessaoReprise: null,
  eventos: [],
  rodada: null,
  resumoReprise: null,
  estadoAtual: "SEARCH",
  timer: null,
};

const TRILHO = ["SEARCH", "SHORTLIST", "PROPERTY_SELECTED", "OFFER_CREATED", "OFFER_SENT",
  "COUNTER_OFFER", "OFFER_ACCEPTED", "KYC_PENDING", "DOCUMENTS_VERIFIED", "CONTRACT_SIGNED",
  "FUNDS_LOCKED", "CONDITIONS_MET", "PAYMENT_RELEASED", "PROPERTY_TRANSFERRED", "COMPLETED"];
const FALHAS = ["OFFER_REJECTED", "ABORTED"];

const reais = (v) => (v === null || v === undefined || v === "") ? "-"
  : "R$ " + Number(v).toLocaleString("pt-BR", { maximumFractionDigits: 0 });
const dolar = (v) => "US$ " + Number(v || 0).toLocaleString("pt-BR",
  { minimumFractionDigits: 4, maximumFractionDigits: 4 });

function limpar(elemento) { while (elemento.firstChild) elemento.removeChild(elemento.firstChild); }

function criar(tag, classe, texto) {
  const elemento = document.createElement(tag);
  if (classe) elemento.className = classe;
  if (texto !== undefined && texto !== null) elemento.textContent = String(texto);
  return elemento;
}

async function pedir(rota, opcoes) {
  const resposta = await fetch(rota, opcoes);
  if (!resposta.ok) {
    let detalhe = resposta.statusText;
    try { detalhe = (await resposta.json()).detail || detalhe; } catch (e) { /* ignora */ }
    throw new Error(detalhe);
  }
  return resposta.json();
}

// ------------------------------------------------------------------ trilho

function desenharTrilho() {
  const lista = $("trilho");
  limpar(lista);
  const atual = ESTADO.estadoAtual;
  const indiceAtual = TRILHO.indexOf(atual);
  TRILHO.forEach((nome, indice) => {
    const item = criar("li", "", nome);
    if (nome === atual) item.className = "atual";
    else if (indiceAtual >= 0 && indice < indiceAtual) item.className = "passou";
    lista.appendChild(item);
  });
  if (FALHAS.includes(atual)) {
    const item = criar("li", "falhou", atual);
    lista.appendChild(item);
  }
  $("estado-atual").textContent = atual;
}

// ------------------------------------------------------------ linha do tempo

function desenharEventos(novos) {
  const lista = $("linha-tempo");
  novos.forEach((evento) => {
    const item = criar("li", evento.tipo);
    const topo = criar("div", "evento-topo");
    topo.appendChild(criar("span", "evento-tipo", evento.tipo));
    const rota = [evento.de, evento.para].filter(Boolean).join(" -> ");
    if (rota) topo.appendChild(criar("span", "evento-rota", rota));
    if (evento.custo_usd) topo.appendChild(criar("span", "evento-custo", dolar(evento.custo_usd)));
    item.appendChild(topo);
    item.appendChild(criar("p", "evento-motivo", evento.motivo || ""));
    const dados = evento.dados || {};
    if (evento.tipo === "chamada" && dados.modelo_roteado) {
      const detalhe = "capacidade pedida: " + dados.capacidade_pedida
        + " | modelo escolhido pela NeuraLake: " + dados.modelo_roteado
        + (dados.plano_b ? " | PLANO B: " + dados.motivo_plano_b : "");
      item.appendChild(criar("p", "dica", detalhe));
    }
    lista.appendChild(item);
  });
  if (novos.length) lista.lastChild.scrollIntoView({ block: "nearest" });
}

function recontar() {
  const placar = { decisao: 0, repasse: 0, humano: 0, verificacao: 0 };
  let custo = 0, auto = 0, chamadas = 0;
  ESTADO.eventos.forEach((evento) => {
    if (placar[evento.tipo] !== undefined) placar[evento.tipo] += 1;
    custo += Number(evento.custo_usd || 0);
    if (evento.tipo === "chamada") {
      chamadas += 1;
      if ((evento.dados || {}).capacidade_pedida === "auto") auto += 1;
    }
  });
  $("p-decisoes").textContent = placar.decisao;
  $("p-repasses").textContent = placar.repasse;
  $("p-humanos").textContent = placar.humano;
  $("p-verificacoes").textContent = placar.verificacao;
  $("custo-total").textContent = dolar(custo);
  $("contador-auto").textContent = auto + " de " + chamadas;
}

// -------------------------------------------------------------- lado direito

function desenharCarteiras(carteiras) {
  const corpo = $("carteiras");
  limpar(corpo);
  carteiras
    .filter((c) => c.gasto_inferencia_usd > 0 || c.honorario_usd > 0 || c.retido_usd > 0)
    .sort((a, b) => b.gasto_inferencia_usd - a.gasto_inferencia_usd)
    .forEach((carteira) => {
      const linha = criar("tr");
      linha.appendChild(criar("td", "", carteira.nome));
      linha.appendChild(criar("td", "", dolar(carteira.gasto_inferencia_usd)));
      linha.appendChild(criar("td", "", dolar(carteira.honorario_usd)));
      const retido = criar("td", carteira.retido_usd > 0 ? "erro" : "", dolar(carteira.retido_usd));
      linha.appendChild(retido);
      corpo.appendChild(linha);
    });
}

function desenharEscrow(escrow) {
  $("escrow-saldo").textContent = escrow && escrow.saldo_brl
    ? reais(escrow.saldo_brl) + " reservados" : "Sem reserva";
  const lista = $("escrow");
  limpar(lista);
  ((escrow || {}).lancamentos || []).forEach((lancamento) => {
    const item = criar("li");
    item.appendChild(criar("b", "", lancamento.tipo + " " + reais(lancamento.valor_brl)));
    item.appendChild(criar("div", "dica", lancamento.motivo || ""));
    lista.appendChild(item);
  });
}

function desenharRecibos(contratos) {
  const lista = $("recibos");
  limpar(lista);
  (contratos || []).forEach((recibo) => {
    const item = criar("li");
    item.appendChild(criar("b", "", recibo.agente_nome + " - " + recibo.skill));
    const conta = "pago " + dolar(recibo.pago_usd) + " de " + dolar(recibo.preco_usd)
      + " | " + recibo.itens_provados + " de " + recibo.itens_pedidos + " provados";
    item.appendChild(criar("div", "", conta));
    if (recibo.retido_usd > 0) {
      item.appendChild(criar("div", "erro", "retido " + dolar(recibo.retido_usd)
        + ": " + (recibo.motivo || "")));
    }
    lista.appendChild(item);
  });
}

// --------------------------------------------------------------- lado esquerdo

function desenharPedido(rodada) {
  if (!rodada.pedido) { $("passo-pedido").hidden = true; return; }
  $("passo-pedido").hidden = false;
  const lista = $("pedido-lista");
  limpar(lista);
  const rotulos = {
    tipo: "Tipo", cidade: "Cidade", bairros: "Bairros", preco_max: "Preço máximo",
    quartos_min: "Quartos", vagas_min: "Vagas", area_min: "Área mínima",
    objetivo: "Objetivo", financiamento: "Financiamento",
  };
  Object.keys(rotulos).forEach((chave) => {
    let valor = rodada.pedido[chave];
    if (valor === null || valor === undefined || valor === "") return;
    if (chave === "preco_max") valor = reais(valor);
    if (chave === "area_min") valor = valor + " m2";
    if (chave === "financiamento") valor = valor ? "sim" : "não";
    if (Array.isArray(valor)) valor = valor.join(", ");
    lista.appendChild(criar("dt", "", rotulos[chave]));
    lista.appendChild(criar("dd", "", valor));
  });
  $("suposicoes").textContent = (rodada.suposicoes || []).length
    ? "Assumiu: " + rodada.suposicoes.join(" | ") : "";
}

function desenharShortlist(rodada) {
  const caixa = $("passo-shortlist");
  if (!rodada.shortlist || !rodada.shortlist.length) { caixa.hidden = true; return; }
  caixa.hidden = false;
  const lista = $("shortlist");
  limpar(lista);
  rodada.shortlist.forEach((imovel) => {
    const cartao = criar("div", "imovel" + (rodada.escolha === imovel.property_id ? " escolhido" : ""));
    const topo = criar("div", "imovel-topo");
    topo.appendChild(criar("span", "imovel-preco", reais(imovel.preco)));
    topo.appendChild(criar("span", "imovel-dados",
      imovel.area + " m2 | " + imovel.quartos + " quartos | " + imovel.vagas + " vagas"));
    cartao.appendChild(topo);
    cartao.appendChild(criar("div", "imovel-dados", imovel.localizacao));
    cartao.appendChild(criar("p", "imovel-motivo", imovel.motivo || ""));

    const selos = criar("div", "imovel-selos");
    selos.appendChild(criar("span", "selo ok", "documentação: " + imovel.documentacao_status));
    selos.appendChild(criar("span", "selo ok", imovel.disponibilidade));
    selos.appendChild(criar("span", "selo", "indicado por " + imovel.indicado_por));
    const comparacao = imovel.comparacao_preco;
    if (comparacao) {
      const percentual = Math.round(comparacao.variacao * 100);
      selos.appendChild(criar("span", "selo " + (percentual <= 0 ? "ok" : "alerta"),
        (percentual <= 0 ? percentual : "+" + percentual) + "% x mediana do bairro"));
    }
    cartao.appendChild(selos);

    const podeEscolher = (!rodada.escolha || rodada.estado === "OFFER_REJECTED");
    if (podeEscolher && ESTADO.modo === "ao-vivo") {
      const botao = criar("button", "", "Escolher este");
      botao.addEventListener("click", () => escolher(imovel.property_id, imovel.preco));
      cartao.appendChild(botao);
    }
    lista.appendChild(cartao);
  });
}

function desenharNegociacao(rodada) {
  const caixa = $("passo-negociacao");
  if (!rodada.negociacao || !rodada.negociacao.length) { caixa.hidden = true; return; }
  caixa.hidden = false;
  const lista = $("negociacao");
  limpar(lista);
  rodada.negociacao.forEach((jogada) => {
    const ehComprador = ["oferta", "aceitar", "desistir"].includes(jogada.acao);
    const item = criar("li", ehComprador ? "comprador" : "vendedor");
    item.appendChild(criar("b", "", "rodada " + jogada.rodada + " | " + jogada.de
      + " | " + jogada.acao + " " + reais(jogada.valor)));
    item.appendChild(criar("div", "", jogada.mensagem || ""));
    item.appendChild(criar("div", "dica", jogada.motivo || ""));
    if (jogada.violacao && jogada.violacao.length) {
      item.appendChild(criar("div", "erro",
        "jogada fora da regra, descartada: " + jogada.violacao.join("; ")));
    }
    lista.appendChild(item);
  });
}

function desenharFim(rodada) {
  const caixa = $("passo-fim");
  const terminou = ["COMPLETED", "ABORTED", "OFFER_REJECTED"].includes(rodada.estado);
  if (!terminou) { caixa.hidden = true; return; }
  caixa.hidden = false;
  if (rodada.estado === "COMPLETED") {
    $("fim-titulo").textContent = "Compra concluída";
    $("fim-titulo").className = "ok";
    $("fim-texto").textContent = "Imóvel " + rodada.escolha + " por " + reais(rodada.preco_acordado)
      + ". KYC, contrato, escritura e escrow são simulados.";
  } else {
    $("fim-titulo").textContent = rodada.estado === "OFFER_REJECTED"
      ? "Sem acordo" : "Rodada interrompida";
    $("fim-titulo").className = "erro";
    $("fim-texto").textContent = rodada.erro || "";
  }
  const lista = $("condicoes");
  limpar(lista);
  const condicoes = (rodada.pacote || {}).condicoes || [];
  condicoes.forEach((condicao) => {
    const item = criar("li", condicao.status === "atendida" ? "atendida" : "");
    item.appendChild(criar("b", "", condicao.nome));
    item.appendChild(criar("div", "dica", condicao.motivo || ""));
    lista.appendChild(item);
  });
}

function desenharRodada(rodada) {
  ESTADO.rodada = rodada;
  ESTADO.estadoAtual = rodada.estado;
  desenharTrilho();
  desenharPedido(rodada);
  desenharShortlist(rodada);
  desenharNegociacao(rodada);
  desenharFim(rodada);
  desenharEscrow(rodada.escrow);
  desenharRecibos(rodada.contratos);
  $("passo-oferta").hidden = !(rodada.estado === "PROPERTY_SELECTED" && ESTADO.modo === "ao-vivo");
  if (rodada.estado === "PROPERTY_SELECTED") $("botao-ofertar").disabled = false;
  if (rodada.memoria_usada) {
    $("subtitulo").textContent = "Segundo comprador: a busca veio da memória do orquestrador. "
      + "A primeira custou " + dolar(rodada.memoria_usada.custo_original_usd)
      + "; esta custou US$ 0,0000 em busca.";
  }
}

// ------------------------------------------------------------------- ações

async function buscar() {
  const frase = $("frase").value.trim();
  if (!frase) return;
  $("botao-buscar").disabled = true;
  try {
    const criada = await pedir("/orchestrator/rodadas", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ frase }),
    });
    ESTADO.rodadaId = criada.rodada_id;
    ESTADO.since = 0;
    ESTADO.eventos = [];
    limpar($("linha-tempo"));
  } catch (erro) {
    $("botao-buscar").disabled = false;
    alert("Não consegui começar: " + erro.message);
  }
}

async function escolher(propertyId, preco) {
  try {
    const rodada = await pedir("/orchestrator/rodadas/" + ESTADO.rodadaId + "/escolha", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ property_id: propertyId }),
    });
    desenharRodada(rodada);
    const teto = Math.round(preco * 0.97 / 10000) * 10000;
    $("teto").value = teto;
    $("oferta-min").value = Math.round(teto * 0.9 / 10000) * 10000;
  } catch (erro) {
    alert("Não consegui registrar a escolha: " + erro.message);
  }
}

async function ofertar() {
  const teto = Number($("teto").value);
  const ofertaMin = Number($("oferta-min").value);
  if (!teto) { alert("Diga o teto de preço."); return; }
  if (ofertaMin && ofertaMin > teto) {
    alert("A oferta mínima não pode ser maior que o teto.");
    return;
  }
  $("botao-ofertar").disabled = true;
  try {
    const rodada = await pedir("/orchestrator/rodadas/" + ESTADO.rodadaId + "/oferta", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ teto_preco: teto, oferta_min: ofertaMin || null,
                             prazo_dias: Number($("prazo").value) || 60 }),
    });
    desenharRodada(rodada);
  } catch (erro) {
    $("botao-ofertar").disabled = false;
    alert("Não consegui enviar a oferta: " + erro.message);
  }
}

// ------------------------------------------------------------------ polling

async function passoAoVivo() {
  if (!ESTADO.rodadaId) return;
  const pacote = await pedir("/orchestrator/eventos?since=" + ESTADO.since
    + "&rodada_id=" + ESTADO.rodadaId);
  if (pacote.eventos.length) {
    ESTADO.since = pacote.ultimo_seq;
    ESTADO.eventos = ESTADO.eventos.concat(pacote.eventos);
    desenharEventos(pacote.eventos);
    recontar();
  }
  const rodada = await pedir("/orchestrator/rodadas/" + ESTADO.rodadaId);
  desenharRodada(rodada);
  const carteiras = await pedir("/orchestrator/carteiras");
  desenharCarteiras(carteiras.carteiras);
}

async function passoReprise() {
  if (!ESTADO.sessaoReprise) return;
  const pacote = await pedir("/orchestrator/reprises/" + ESTADO.sessaoReprise
    + "/eventos?since=" + ESTADO.since);
  $("rotulo-reprise").textContent = pacote.rotulo;
  if (pacote.eventos.length) {
    ESTADO.since = pacote.ultimo_seq;
    ESTADO.eventos = ESTADO.eventos.concat(pacote.eventos);
    desenharEventos(pacote.eventos);
    recontar();
  }
  if (pacote.estado) { ESTADO.estadoAtual = pacote.estado; desenharTrilho(); }
  const resumo = pacote.resumo || {};
  const vistos = new Set(ESTADO.eventos.map((e) => e.estado));
  const parcial = {
    estado: pacote.estado || resumo.estado,
    pedido: vistos.has("SEARCH") ? resumo.pedido : null,
    suposicoes: resumo.suposicoes,
    shortlist: (vistos.has("SHORTLIST") || vistos.has("PROPERTY_SELECTED")) ? resumo.shortlist : [],
    escolha: resumo.escolha,
    negociacao: vistos.has("OFFER_SENT") || vistos.has("COUNTER_OFFER") ? resumo.negociacao : [],
    preco_acordado: resumo.preco_acordado,
    pacote: resumo.pacote,
    contratos: resumo.contratos,
    escrow: vistos.has("FUNDS_LOCKED") ? resumo.escrow : { saldo_brl: 0, lancamentos: [] },
    erro: resumo.erro,
    memoria_usada: resumo.memoria_usada,
  };
  desenharRodada(parcial);
}

async function laco() {
  try {
    if (ESTADO.modo === "ao-vivo") await passoAoVivo();
    else await passoReprise();
  } catch (erro) {
    console.error("falha no polling", erro);
  }
}

// -------------------------------------------------------------------- modo

async function entrarAoVivo() {
  ESTADO.modo = "ao-vivo";
  ESTADO.sessaoReprise = null;
  ESTADO.since = 0;
  ESTADO.eventos = [];
  limpar($("linha-tempo"));
  recontar();
  $("faixa-reprise").hidden = true;
  $("botao-ao-vivo").className = "ligado";
  $("botao-reprise").className = "";
  $("lista-reprises").hidden = true;
  $("passo-frase").hidden = false;
  $("botao-buscar").disabled = false;
}

async function entrarReprise() {
  const lista = $("lista-reprises");
  try {
    const pacote = await pedir("/orchestrator/reprises");
    limpar(lista);
    if (!pacote.gravacoes.length) {
      alert("Não há gravação nenhuma ainda. Rode uma vez ao vivo até o fim.");
      return;
    }
    pacote.gravacoes.forEach((gravacao) => {
      const opcao = criar("option", "", gravacao.arquivo + " | " + gravacao.estado_final
        + " | " + Math.round(gravacao.duracao_total_s) + "s | " + gravacao.eventos + " eventos");
      opcao.value = gravacao.arquivo;
      lista.appendChild(opcao);
    });
    lista.hidden = false;
    await abrirReprise(lista.value);
  } catch (erro) {
    alert("Não consegui listar as gravações: " + erro.message);
  }
}

async function abrirReprise(arquivo) {
  const sessao = await pedir("/orchestrator/reprises", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ arquivo, velocidade: 3.0 }),
  });
  ESTADO.modo = "reprise";
  ESTADO.sessaoReprise = sessao.sessao_id;
  ESTADO.since = 0;
  ESTADO.eventos = [];
  limpar($("linha-tempo"));
  recontar();
  $("rotulo-reprise").textContent = sessao.rotulo;
  $("faixa-reprise").hidden = false;
  $("botao-reprise").className = "ligado";
  $("botao-ao-vivo").className = "";
  $("passo-frase").hidden = true;
  $("passo-oferta").hidden = true;
}

// ------------------------------------------------------------------- início

$("botao-buscar").addEventListener("click", buscar);
$("botao-ofertar").addEventListener("click", ofertar);
$("botao-ao-vivo").addEventListener("click", entrarAoVivo);
$("botao-reprise").addEventListener("click", entrarReprise);
$("lista-reprises").addEventListener("change", (evento) => abrirReprise(evento.target.value));

desenharTrilho();
recontar();
ESTADO.timer = setInterval(laco, 1000);
