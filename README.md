# engine-yir

A Yir (https://yir.ai) engine for the F-Capacitor / Helmer Generators: one key (`YIR_API_KEY`) for the image and video models Yir routes, with Yir's own failover between channels.

Seven MiniMax H3 models, one TOML each under `engine_yir/endpoints/`, written from Yir's model contracts
(`GET https://gateway.yir.ai/v1/models/minimax/<model>?view=contract`):

- video (`VID-Models/`): `minimax/minimax-h3-max`, `minimax/h3-max-turbo`, `minimax/minimax-h3`,
  `minimax/minimax-h3-highspeed`, `minimax/minimax-h3-lite`;
- image (`IMG-Models/`): `minimax/minimax-h3-image`, `minimax/minimax-h3-image-highspeed`.

Each TOML's `[inputs.<type>]` tables copy the contract: the reference roles and parameter values each input type
(`text`, `image`, `reference`) takes. A prompt alone runs as `text`; pictures run as a start (and end) frame where the
model takes one, otherwise as reference pictures; the reference slots run as `reference`. Only the chosen type's
parameters, with its allowed values, are sent.

A run submits a Job with an `Idempotency-Key` (`POST /v1/videos/generations` or `/v1/images/generations`), long-polls
`GET /v1/jobs/{id}/status?wait=20`, reads the Job and downloads `result.files[0].url` at once (it is temporary).
The gateway is `https://gateway.yir.ai` unless a profile sets `base_url`.

MIT licence.
