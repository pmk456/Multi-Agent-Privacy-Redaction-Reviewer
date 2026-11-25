# Frontend

Plain HTML with Tailwind from the CDN. No build step and no framework - there are only a
few screens, and a toolchain would cost more than it saves for a prototype.

Open `index.html` in a browser with the backend running on port 8000.

## The rule here

The API never sends an original identifier, so there is nothing to accidentally render.
Keep it that way: display `category` and `risk`, and if you need to refer to a specific
entity use its `entity_id`.

Owner: Pulagampalli Sai Mahima
