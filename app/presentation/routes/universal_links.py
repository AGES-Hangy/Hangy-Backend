from html import escape

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import settings

APPLE_BUNDLE_ID = "br.pucrs.ages.hangy"
ANDROID_PACKAGE_NAME = "br.pucrs.ages.hangy"

router = APIRouter(include_in_schema=False)


def _store_links() -> str:
    links = []
    if settings.app_store_url:
        app_store_url = escape(settings.app_store_url, quote=True)
        links.append(
            f'<a class="secondary" href="{app_store_url}">Baixar na App Store</a>'
        )
    if settings.google_play_url:
        google_play_url = escape(settings.google_play_url, quote=True)
        links.append(
            f'<a class="secondary" href="{google_play_url}">Baixar no Google Play</a>'
        )

    if links:
        return '<div class="stores" aria-label="Baixar o app">{}</div>'.format(
            "".join(links)
        )
    return '<p class="availability">O Hangy ainda não está disponível nas lojas.</p>'


@router.get(
    "/invite/{token}",
    response_class=HTMLResponse,
    status_code=status.HTTP_200_OK,
)
def invite_landing_page(token: str) -> HTMLResponse:
    safe_deep_link = escape(f"{settings.invite_link_base_url}{token}", quote=True)
    html = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Convite para o Hangy</title>
  <style>
    :root {{ color-scheme: light; font-family: system-ui, sans-serif; }}
    body {{
      align-items: center; background: #f7f5ff; display: flex; margin: 0;
      min-height: 100vh; padding: 24px; box-sizing: border-box;
    }}
    main {{
      background: white; border-radius: 20px; box-shadow: 0 12px 36px #2b17521a;
      margin: auto; max-width: 480px; padding: 40px; text-align: center;
    }}
    h1 {{ color: #28164c; font-size: 1.75rem; margin-top: 0; }}
    p {{ color: #554d63; line-height: 1.5; }}
    a {{
      border-radius: 999px; display: block; font-weight: 700; margin-top: 16px;
      padding: 14px 20px; text-decoration: none;
    }}
    .primary {{ background: #6c42d8; color: white; }}
    .secondary {{ border: 2px solid #6c42d8; color: #5530b7; }}
    .availability {{ font-size: .9rem; margin: 24px 0 0; }}
    .stores {{ margin-top: 24px; }}
  </style>
</head>
<body>
  <main>
    <h1>Você foi convidado para um evento no Hangy.</h1>
    <p>Abra o convite no app para ver os detalhes e participar.</p>
    <a class="primary" href="{safe_deep_link}">Abrir no app</a>
    {_store_links()}
  </main>
</body>
</html>
"""
    return HTMLResponse(
        content=html,
        status_code=status.HTTP_200_OK,
        headers={
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/.well-known/apple-app-site-association",
    response_class=JSONResponse,
    status_code=status.HTTP_200_OK,
)
def apple_app_site_association() -> JSONResponse:
    if not settings.apple_team_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    return JSONResponse(
        content={
            "applinks": {
                "details": [
                    {
                        "appIDs": [f"{settings.apple_team_id}.{APPLE_BUNDLE_ID}"],
                        "components": [{"/": "/invite/*"}],
                    }
                ]
            }
        }
    )


@router.get(
    "/.well-known/assetlinks.json",
    response_class=JSONResponse,
    status_code=status.HTTP_200_OK,
)
def android_asset_links() -> JSONResponse:
    if not settings.android_sha256_fingerprints:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    return JSONResponse(
        content=[
            {
                "relation": ["delegate_permission/common.handle_all_urls"],
                "target": {
                    "namespace": "android_app",
                    "package_name": ANDROID_PACKAGE_NAME,
                    "sha256_cert_fingerprints": list(
                        settings.android_sha256_fingerprints
                    ),
                },
            }
        ]
    )


__all__ = [
    "ANDROID_PACKAGE_NAME",
    "APPLE_BUNDLE_ID",
    "android_asset_links",
    "apple_app_site_association",
    "invite_landing_page",
    "router",
]
