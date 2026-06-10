# -*- coding: utf-8 -*-
"""
Carrossel GreenGold - automacao completa (roda no GitHub Actions).

Fluxo: le o artigo mais recente do blog -> IA (Gemini) escreve o carrossel e
escolhe o formato -> desenha os 7 slides (PIL, padrao aprovado) -> posta o
carrossel no Instagram (Graph API). Estado em estado.json evita repetir.

Variaveis de ambiente (secrets do GitHub):
  GEMINI_API_KEY, IG_TOKEN, IG_USER_ID
  REPO (owner/repo, default do github.repository), BRANCH (default main)
  POST_ENABLED = "1" pra postar de verdade (senao so renderiza)
"""
import os, re, json, time, subprocess, urllib.request, urllib.parse, urllib.error
from PIL import Image, ImageDraw, ImageFont

HERE   = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
SLIDES = os.path.join(HERE, "slides")
ESTADO = os.path.join(HERE, "estado.json")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
IG_TOKEN   = os.environ.get("IG_TOKEN", "")
IG_USER    = os.environ.get("IG_USER_ID", "")
REPO       = os.environ.get("REPO", "hrafael5/greengold-carrossel")
BRANCH     = os.environ.get("BRANCH", "main")
POST       = os.environ.get("POST_ENABLED", "0") == "1"
BLOG_API   = "https://greengoldengenharia.com.br/wp-json/wp/v2/posts?per_page=1"

# fotos limpas vetadas (Unsplash, sem chave). A IA escolhe o tema; cai no default se nao reconhecer.
FOTOS = {
    "projeto":    "1503387762-592deb58ef4e",   # engenheiro desenhando plantas
    "tecnico":    "1581092160562-40aa08e78837", # desenho tecnico na prancheta
    "obra":       "1565008447742-97f6f38c985c", # canteiro / torres em obra
    "construcao": "1504307651254-35680f356dfd", # trabalhadores na obra
    "predial":    "1487958449943-2429e8be8625", # predio moderno
}
def foto_url(tema):
    pid = FOTOS.get((tema or "").strip().lower(), FOTOS["projeto"])
    return "https://images.unsplash.com/photo-%s?w=1280&q=80" % pid

# ===================== DESIGN (padrao aprovado, IBM Plex) =====================
BG, GOLD, WHITE, OFF, DIM = (12,36,16), (201,169,110), (255,255,255), (228,224,212), (150,168,150)
def _f(name, size): return ImageFont.truetype(os.path.join(ASSETS, name), size)
F_KICKER = _f("ibm-sb.ttf", 26); F_HBIG = _f("ibm-bold.ttf", 64); F_H = _f("ibm-bold.ttf", 52)
F_SUB = _f("ibm-sb.ttf", 37); F_BODY = _f("ibm-reg.ttf", 35); F_NUM = _f("ibm-bold.ttf", 145)
F_PG = _f("ibm-sb.ttf", 26); F_PILL = _f("ibm-bold.ttf", 33)
W, H, MX = 1080, 1350, 96
CW = W - 2*MX
LOGO = Image.open(os.path.join(ASSETS, "logo.png")).convert("RGBA")
LOGO = LOGO.resize((int(LOGO.width * 50 / LOGO.height), 50), Image.LANCZOS)

def wrap(d, text, fnt, maxw):
    out, cur = [], ""
    for w in str(text).split():
        t = (cur + " " + w).strip()
        if d.textlength(t, font=fnt) <= maxw: cur = t
        else:
            if cur: out.append(cur)
            cur = w
    if cur: out.append(cur)
    return out

def block(d, x, y, text, fnt, fill, maxw, lh):
    for ln in wrap(d, text, fnt, maxw):
        d.text((x, y), ln, font=fnt, fill=fill); y += lh
    return y

def tracked(d, x, y, text, fnt, fill, sp=4):
    for ch in str(text):
        d.text((x, y), ch, font=fnt, fill=fill); x += d.textlength(ch, font=fnt) + sp
    return x

def base():
    img = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(img)
    d.rectangle([28, 28, W-28, H-28], outline=GOLD, width=2)
    return img, d

def footer(img, d, page):
    y = H - 100
    img.paste(LOGO, (W - MX - LOGO.width, y), LOGO)
    d.text((MX, y + 10), "%d / 7" % page, font=F_PG, fill=DIM)

def save(img, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, quality=92)

def cover(data, path, photo=None):
    img, d = base(); x = MX
    used = False
    if photo and os.path.exists(photo):
        try:
            ph = Image.open(photo).convert("RGB")                  # foto limpa (sem texto)
            sc = max(W/ph.width, H/ph.height)
            ph = ph.resize((int(ph.width*sc), int(ph.height*sc)), Image.LANCZOS)
            l = (ph.width-W)//2; t = (ph.height-H)//2
            base_ph = ph.crop((l, t, l+W, t+H)).convert("RGBA")
            ov = Image.new("RGBA", (W, H), (0,0,0,0)); od = ImageDraw.Draw(ov)
            for yy in range(H):                                    # degrade: leve no topo, forte embaixo
                a = 105 if yy < 680 else int(105 + (245-105)*((yy-680)/(H-680)))
                od.line([(0, yy), (W, yy)], fill=(12, 36, 16, a))
            comp = Image.alpha_composite(base_ph, ov).convert("RGB")
            img.paste(comp, (0, 0)); d = ImageDraw.Draw(img)
            d.rectangle([28, 28, W-28, H-28], outline=GOLD, width=2)
            y = 780                                                # UM texto, embaixo
            tracked(d, x, y, str(data["capa_kicker"]).upper(), F_KICKER, GOLD, 4)
            d.rectangle([x, y+50, x+80, y+54], fill=GOLD); y += 100
            block(d, x, y, data["capa_titulo"], F_HBIG, WHITE, CW, 78)
            used = True
        except Exception:
            used = False
    if not used:                                                  # fallback: fundo verde liso
        y = 250
        tracked(d, x, y, str(data["capa_kicker"]).upper(), F_KICKER, GOLD, 4)
        d.rectangle([x, y+50, x+80, y+54], fill=GOLD); y += 110
        y = block(d, x, y, data["capa_titulo"], F_HBIG, WHITE, CW, 78); y += 26
        block(d, x, y, data["capa_subtitulo"], F_SUB, GOLD, CW, 48)
    arr = "arraste  →"
    d.text((W - MX - d.textlength(arr, font=F_SUB), H - 185), arr, font=F_SUB, fill=OFF)
    footer(img, d, 1); save(img, path)

def content(num, title, body, page, path):
    img, d = base(); x = MX
    d.text((x, 150), num, font=F_NUM, fill=GOLD)
    y = 360
    y = block(d, x, y, title, F_H, WHITE, CW, 64); y += 30
    d.rectangle([x, y, x+70, y+4], fill=GOLD); y += 44
    block(d, x, y, body, F_BODY, OFF, CW, 50)
    footer(img, d, page); save(img, path)

def cta(data, path):
    img, d = base(); x, y = MX, 250
    tracked(d, x, y, "FALE COM A GREENGOLD", F_KICKER, GOLD, 4)
    d.rectangle([x, y+50, x+80, y+54], fill=GOLD); y += 120
    y = block(d, x, y, data["cta_titulo"], F_HBIG, WHITE, CW, 78); y += 30
    y = block(d, x, y, data["cta_corpo"], F_BODY, OFF, CW, 50); y += 50
    pw = d.textlength("Link na bio", font=F_PILL) + 64
    d.rounded_rectangle([x, y, x+pw, y+76], radius=38, fill=GOLD)
    d.text((x+32, y+18), "Link na bio", font=F_PILL, fill=BG)
    footer(img, d, 7); save(img, path)

def render(data, outdir, photo=None):
    cover(data, os.path.join(outdir, "slide-1.jpg"), photo)
    for i, s in enumerate(data["slides"][:5]):
        content("%02d" % (i+1), s["titulo"], s["corpo"], i+2, os.path.join(outdir, "slide-%d.jpg" % (i+2)))
    cta(data, os.path.join(outdir, "slide-7.jpg"))

# ===================== DADOS (blog + IA) =====================
def http(url, data=None, headers=None):
    h = dict(UA);  h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read()

def latest_article():
    arr = json.loads(http(BLOG_API))
    p = arr[0]
    title = re.sub(r"<[^>]+>", "", p["title"]["rendered"])
    body = re.sub(r"<[^>]+>", " ", p["content"]["rendered"])
    body = re.sub(r"\s+", " ", body).strip()[:4000]
    img = None
    try:
        img = p["_embedded"]["wp:featuredmedia"][0]["source_url"]
    except Exception:
        pass
    return {"id": p["id"], "title": title, "content": body, "link": p["link"], "img": img}

PROMPT = """Voce e redator de redes sociais da GreenGold Engenharia Multidisciplinar (instalacoes prediais, BIM, eletrico, hidrossanitario, SPDA, PPCI, com ART no CREA).
A partir do artigo, crie um CARROSSEL de Instagram que ENGAJA e as pessoas COMPARTILHAM.
Escolha o MELHOR formato entre: erros, passo a passo, checklist, mitos x verdades.
Regras:
- PT-BR formal, 100 por cento acentuado.
- PROIBIDO travessao. Use virgula, ponto ou parenteses.
- NAO citar estados (MG, SP, RJ, ES).
- 1 ideia por slide, frases curtas.
- Os titulos dos slides NAO comecam com numero (o slide ja tem o numero).
- Exatamente 5 slides de conteudo. Capa com gancho forte, CTA no final.
- Tecnicamente correto, cite a NBR quando fizer sentido.
- Escolha tema_foto pela cara do artigo, UM de: projeto, tecnico, obra, construcao, predial.
Responda APENAS JSON:
{"formato":"...","tema_foto":"projeto","capa_kicker":"a NOTICIA/assunto especifico do artigo, bem curto (a materia, ex: Construi Mais Brasil, NBR 13714, AVCB)","capa_titulo":"o gancho que engaja, curto","capa_subtitulo":"...","slides":[{"titulo":"...","corpo":"..."}],"cta_titulo":"...","cta_corpo":"...","legenda":"2 a 3 frases + 8 hashtags sem localizacao"}
ARTIGO:
Titulo: %s
Conteudo: %s"""

def _gemini_call(model, art):
    body = json.dumps({"contents":[{"parts":[{"text": PROMPT % (art["title"], art["content"])}]}],
                       "generationConfig":{"responseMimeType":"application/json","temperature":0.7}}).encode()
    url = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s" % (model, GEMINI_KEY)
    resp = json.loads(http(url, data=body, headers={"Content-Type":"application/json"}))
    return json.loads(resp["candidates"][0]["content"]["parts"][0]["text"])

def gerar_ia(art):
    # flash primeiro; se estourar cota (429), espera e cai pro flash-lite (cota separada)
    for model in ("gemini-2.5-flash", "gemini-2.5-flash-lite"):
        for attempt in range(3):
            try:
                return _gemini_call(model, art)
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    print("  %s 429 (cota), aguardando..." % model); time.sleep(12); continue
                raise
    raise RuntimeError("Gemini sem cota nos dois modelos agora")

# ===================== INSTAGRAM =====================
def ig(path, fields):
    url = "https://graph.facebook.com/v20.0/" + path
    body = urllib.parse.urlencode(fields).encode()
    try:
        return json.loads(http(url, data=body))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode())

def post_carousel(urls, caption):
    children = []
    for u in urls:
        r = ig("%s/media" % IG_USER, {"image_url": u, "is_carousel_item": "true", "access_token": IG_TOKEN})
        if "id" not in r: raise RuntimeError("erro child %s: %s" % (u, r))
        children.append(r["id"])
    r = ig("%s/media" % IG_USER, {"media_type": "CAROUSEL", "children": ",".join(children),
                                  "caption": caption, "access_token": IG_TOKEN})
    if "id" not in r: raise RuntimeError("erro container: %s" % r)
    time.sleep(3)
    pub = ig("%s/media_publish" % IG_USER, {"creation_id": r["id"], "access_token": IG_TOKEN})
    if "id" not in pub: raise RuntimeError("erro publish: %s" % pub)
    return pub["id"]

# ===================== GIT =====================
def git(*args):
    subprocess.run(["git", *args], cwd=HERE, check=True)

def aguarda_urls(urls):
    for u in urls:
        for _ in range(20):
            try:
                req = urllib.request.Request(u, headers=UA, method="HEAD")
                if urllib.request.urlopen(req, timeout=20).status == 200: break
            except Exception: pass
            time.sleep(3)

# ===================== MAIN =====================
def main():
    estado = json.load(open(ESTADO, encoding="utf-8")) if os.path.exists(ESTADO) else {"processados": []}
    art = latest_article()
    print("Artigo mais recente:", art["id"], art["title"][:60])
    if art["id"] in estado["processados"]:
        print("Ja processado, nada a fazer."); return
    data = gerar_ia(art)
    print("Formato escolhido pela IA:", data.get("formato"))
    outdir = os.path.join(SLIDES, str(art["id"]))
    os.makedirs(outdir, exist_ok=True)
    photo = None
    try:
        photo = os.path.join(outdir, "cover-photo.jpg")
        open(photo, "wb").write(http(foto_url(data.get("tema_foto"))))
        print("Foto limpa da capa baixada (tema: %s)" % data.get("tema_foto"))
    except Exception as e:
        print("Foto falhou, usando fundo verde:", e); photo = None
    render(data, outdir, photo)
    print("7 slides renderizados em", outdir)
    json.dump(data, open(os.path.join(outdir, "carrossel.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # commita os slides sempre (versiona + deixa visivel pra revisao)
    git_ok = True
    try:
        git("add", "slides"); git("commit", "-m", "render artigo %s" % art["id"]); git("push")
    except Exception as e:
        git_ok = False
        print("git falhou (rodando local?):", e)

    if not POST:
        print("POST_ENABLED desligado: renderizei e commitei pra revisao, sem postar."); return
    if not git_ok:
        # sem commit os slides nao existem no raw.githubusercontent: postar daria 404 na Meta
        raise RuntimeError("commit/push dos slides falhou; abortando o post pra nao mandar URL 404 pra Meta")

    urls = ["https://raw.githubusercontent.com/%s/%s/slides/%s/slide-%d.jpg" % (REPO, BRANCH, art["id"], i) for i in range(1, 8)]
    aguarda_urls(urls)
    mid = post_carousel(urls, data.get("legenda", art["title"]))
    print("POSTADO no Instagram, media id:", mid)
    estado["processados"].append(art["id"])
    json.dump(estado, open(ESTADO, "w", encoding="utf-8"), ensure_ascii=False)
    git("add", "estado.json"); git("commit", "-m", "estado %s" % art["id"]); git("push")

if __name__ == "__main__":
    main()
