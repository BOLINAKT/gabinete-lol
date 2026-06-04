# Logos dos times

Coloque aqui os logos dos times (PNG/WEBP/JPG/SVG). O nome do arquivo é o nome do
time **normalizado**: minúsculo, só letras e números (sem espaço/pontuação).

Exemplos:
- `Gen.G`  → `geng.png`
- `T1`     → `t1.png`
- `LNG Esports` → `lngesports.png`
- `Bilibili Gaming` → `bilibiligaming.png`

Quando o arquivo existe, ele aparece ao lado do nome do time na UI (cabeçalho do
confronto, etc.). Quando **não** existe, a UI cai automaticamente no badge de
iniciais ciano — então nada quebra se faltar um logo.

Para descobrir a chave exata de um time:
```python
from app_core.team_logos_core import _norm
print(_norm("Gen.G"))   # -> geng
```

Tamanho recomendado: ~128x128 px, fundo transparente (PNG). Arquivos pequenos
(o logo é embutido como data-URI na página).
