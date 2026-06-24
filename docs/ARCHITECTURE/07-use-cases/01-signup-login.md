# Use Case: Signup, Email Verification, Login, Token Refresh

> Authentication flow: email signup, verification, login, JWT + refresh tokens.

## Diagram

```mermaid
sequenceDiagram
    participant User as User
    participant Frontend as Frontend (/signup)
    participant API as POST /api/v2/auth/signup
    participant DB as PostgreSQL
    participant Email as Email Service
    participant JWT as JWTService
    
    User->>Frontend: Enter email + password
    Frontend->>API: POST /signup {email, password, name}
    API->>API: validate_email_format()
    API->>DB: SELECT * FROM users WHERE email=?
    DB-->>API: null (does not exist)
    API->>API: hash_password(password) via Argon2id
    API->>DB: CREATE User {id='usr_...', email, password_hash, organization_id='org_...'}
    DB-->>API: user + organization created
    API->>DB: CREATE APIKey (org default key)
    API->>DB: CREATE Workspace (org default workspace)
    API->>JWT: encode_access_token(user_id, org_id)
    JWT-->>API: access_token (JWT)
    API->>JWT: encode_refresh_token(user_id)
    JWT-->>API: refresh_token (opaque)
    API->>DB: INSERT RefreshToken {user_id, token_hash, revoked_at=null}
    API->>Email: send_verify_email_link {email, token}
    Email-->>User: Email with link: /verify?token=...
    API->>Frontend: 201 {access_token, refresh_token, user}
    
    Frontend->>Frontend: Store tokens in httpOnly cookies
    Frontend->>Frontend: Redirect to /verify-email
    
    User->>Email: Click verification link
    Email->>Frontend: Redirects to /verify?code=...
    Frontend->>API: POST /verify-email {code}
    API->>DB: VERIFY email_verification_token(code)
    DB->>DB: UPDATE users SET email_verified=true
    DB-->>API: user verified
    API->>Frontend: 200 {message: "Email verified"}
    
    note over User,API: --- LOGIN FLOW ---
    
    User->>Frontend: Enter email + password
    Frontend->>API: POST /login {email, password}
    API->>DB: SELECT * FROM users WHERE email=?
    DB-->>API: user found
    API->>API: verify_password(input, user.password_hash)
    alt Password OK
        API->>API: reset failed_login_attempts
        API->>JWT: encode tokens
        API->>DB: INSERT RefreshToken
        API->>Frontend: 200 {access_token, refresh_token}
    else Password WRONG
        API->>API: increment failed_login_attempts
        alt attempts >= MAX (5)
            API->>DB: UPDATE users SET locked_until = now() + 15min
        end
        API->>Frontend: 401 "Invalid credentials"
    end
    
    Frontend->>Frontend: Store tokens in httpOnly cookies
    Frontend->>Frontend: Redirect to /dashboard
    
    note over User,API: --- REFRESH TOKEN FLOW ---
    
    Frontend->>API: GET /me {cookies: {refresh_token}}
    alt Access token expired
        API->>API: JWTService.decode(access_token) → exp check
        API->>DB: SELECT * FROM refresh_tokens WHERE token_hash=?
        DB-->>API: RefreshToken (revoked_at IS NULL)
        API->>JWT: encode_new_access_token(user_id, org_id)
        JWT-->>API: new access_token
        API->>Frontend: 200 {user, new_access_token}
    else Access token valid
        API->>Frontend: 200 {user}
    end
```

## Critical Points

### Validation
- **Email format**: RFC 5322 regex
- **Password strength**: minimum 8 characters, complexity (no in-app validation, hash only)
- **Rate limiting**: 5 signup/login per IP per minute (check_rate_limit)

### Security
- **Argon2id**: memory + time params via config (not bcrypt)
- **JWT**: HS256 with JWT_SECRET, exp=1h
- **Refresh tokens**: SHA-256 hash in DB, opaque to the client, never expire (revoke only)
- **Cookies**: httpOnly + Secure (prod), SameSite=Lax
- **Account lockout**: 5 failures → 15 min lock (failed_login_attempts counter)

### Recovery
- If refresh_token revoked (logout): 401 → re-login required
- If refresh_token does not exist: 401 (token expired or invalid)
- Logout: UPDATE refresh_tokens SET revoked_at=now()

## Relevant Files

- `app/api/v2/auth.py:signup()` — signup + org creation + APIKey
- `app/api/v2/auth.py:verify_email()` — consume token, mark verified
- `app/api/v2/auth.py:login()` — authentication + token issuance
- `app/api/v2/auth.py:refresh()` — renew access token
- `app/services/auth/password_service.py:PasswordService` — hash/verify Argon2id
- `app/services/auth/jwt_service.py:JWTService` — encode/decode JWT
- `app/models/user.py:User` — password_hash, email_verified, locked_until
- `app/models/refresh_token.py:RefreshToken` — token_hash, revoked_at
- `app/models/organization.py:Organization` — created at signup
