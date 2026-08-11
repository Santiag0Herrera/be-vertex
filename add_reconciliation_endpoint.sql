-- Register the manual reconciliation endpoint in PermissionMiddleware.
-- Replace :permission_id with the permission required for internal users.
INSERT INTO endpoints (path, perm_id)
VALUES ('/trx/reconcile-pending', :permission_id)
ON CONFLICT (path) DO UPDATE
SET perm_id = EXCLUDED.perm_id;
