# LearnHub - Frontend ↔ Backend Integration Guide

The backend serves these integration scripts automatically at:

- `/js/api.js`  → `js/api.js` (API client with localStorage fallback)
- `/js/auth.js` → `js/auth.js` (login/register helpers)

> Do NOT modify the existing HTML files in place to test - the pages work
> against the backend as soon as the two script tags below are added,
> because `api.js` falls back to the current localStorage behaviour when
> the backend is not reachable.

When the repo is served through the backend (`python3 backend/app.py` then
open `http://localhost:8000`), add the tags right **before** the existing
`script.js` tag on each page.

## Script tags to add (per page)

### Every page (api client)
```html
<script src="/js/api.js"></script>
```

### login.html and register.html only (auth helpers)
```html
<script src="/js/api.js"></script>
<script src="/js/auth.js"></script>
```

## Exact insertion points

| Page | Existing line | Insert before it |
|---|---|---|
| `index.html` | `<script src="js/script.js"></script>` (line ~963) | `<script src="/js/api.js"></script>` |
| `courses.html` | `<script src="script.js"></script>` (line 233) | `<script src="/js/api.js"></script>` |
| `course-details.html` | `<script src="script.js"></script>` (line 86) | `<script src="/js/api.js"></script>` |
| `cart.html` | `<script src="script.js"></script>` (line 86) | `<script src="/js/api.js"></script>` |
| `checkout.html` | `<script src="script.js"></script>` (line 161) | `<script src="/js/api.js"></script>` |
| `my-courses.html` | `<script src="script.js"></script>` (line 97) | `<script src="/js/api.js"></script>` |
| `wishlist.html` | `<script src="script.js"></script>` (line 93) | `<script src="/js/api.js"></script>` |
| `profile.html` | `<script src="script.js"></script>` (line 97) | `<script src="/js/api.js"></script>` |
| `payment-success.html` | `<script src="script.js"></script>` (line 89) | `<script src="/js/api.js"></script>` |
| `login.html` | `<script src="script.js"></script>` (line 112) | `<script src="/js/api.js"></script>` then `<script src="/js/auth.js"></script>` |
| `register.html` | `<script src="script.js"></script>` (line 112) | `<script src="/js/api.js"></script>` then `<script src="/js/auth.js"></script>` |

## Wiring the forms

Both `login.html` and `register.html` already contain a `<form id="registerForm">`
with `#registerName`, `#registerEmail`, `#registerPassword`. After adding the
script tags, add one inline snippet at the bottom of each page:

**login.html** - signs the user in, redirects to `index.html`:
```html
<script>
  LearnHubAuth.wireLoginForm("registerForm", "index.html");
</script>
```

**register.html** - creates the account, redirects to `index.html`:
```html
<script>
  LearnHubAuth.wireRegisterForm("registerForm", "index.html");
</script>
```

## Using the API from page scripts

```js
// courses page - load courses from the DB (falls back to script.js data offline)
const courses = await LearnHubAPI.getCourses();

// course details - lessons for a course
const lessons = await LearnHubAPI.getLessons(courseId);

// cart page
await LearnHubAPI.addToCart(courseId);
const items = await LearnHubAPI.getCart();
await LearnHubAPI.removeFromCart(cartItemId);

// checkout - enrols the user in all cart courses, clears the cart
const order = await LearnHubAPI.checkout();

// my courses - enrolments with progress
const myCourses = await LearnHubAPI.getMyCourses();
await LearnHubAPI.updateProgress(enrollmentId, 50);

// auth state
LearnHubAuth.isSignedIn();
LearnHubAuth.requireAuth(); // redirect to login.html when signed out
```

## Auth details

- Token is stored in `localStorage` as `lh_token`; the user profile as `lh_user`.
- Every authenticated call sends `Authorization: Bearer <token>`.
- Legacy keys (`currentUser`, `cart`, `wishlist`) are left untouched, so the
  static site keeps working exactly as before when the backend is offline.
