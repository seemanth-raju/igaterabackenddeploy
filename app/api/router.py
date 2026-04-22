from fastapi import APIRouter

from app.api.services.access.route import router as access_router
from app.api.services.auth.route import router as auth_router
from app.api.services.companies.route import router as companies_router
from app.api.services.device_mapping.route import router as device_mapping_router
from app.api.services.devices.route import router as devices_router
from app.api.services.groups.route import router as groups_router
from app.api.services.logs.route import router as logs_router
from app.api.services.sites.route import router as sites_router
from app.api.services.push.route import router as push_router
from app.api.services.tenants.route import router as tenants_router
from app.api.services.users.route import router as users_router

api_router = APIRouter(prefix="/api")
api_router.include_router(auth_router)
api_router.include_router(companies_router)
api_router.include_router(sites_router)
api_router.include_router(devices_router)
api_router.include_router(users_router)
api_router.include_router(tenants_router)
api_router.include_router(groups_router)
api_router.include_router(access_router)
api_router.include_router(device_mapping_router)
api_router.include_router(push_router)
api_router.include_router(logs_router)
