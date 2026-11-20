# Provenance of the coops-data pack

The pack and the module `coops` are written by hand from the CO-OPS Data Retrieval API
documentation; the vectors by `tools/gen/usgov2-vectors.py` from responses written for
them. No source file is kept in this repository. Read on 2026-11-20.

## Sources

| Document | Address | SHA-256 of the page as served |
|---|---|---|
| CO-OPS Data Retrieval API | https://api.tidesandcurrents.noaa.gov/api/prod/ | `2f35c273fdb3eeca2aa98111d0ed62998500c2ed9f4c507b0543d919dd6b4da5` |
| Data API Response Help (the columns) | https://api.tidesandcurrents.noaa.gov/api/prod/responseHelp.html | `c934a7921f56b80bbd5b05701795357a97cb5cb3c692931c3d96e8194976ba69` |
| CO-OPS Disclaimers | https://tidesandcurrents.noaa.gov/disclaimers.html | `4af265156e195fda2a8c4457af5bd2f73b74d70cd9219f3a4ae94d2d2543363c` |
| National Ocean Service Website Disclaimers | https://oceanservice.noaa.gov/disclaimer.html | `df2867bd3508733d78a2f7db85f44ae985ec66029d0eb4ba954088fc197fd532` |

The JSON types of the members (every value a string) were checked against live responses
of four products read on 2026-11-20; only their shape was looked at, and no value of them
is in this repository.

## License

The API and its documentation are works of the United States Government (NOAA National
Ocean Service, Center for Operational Oceanographic Products and Services; 17 U.S.C. 105).
The National Ocean Service, of which CO-OPS is a part, states:

> Information presented on this website is considered public information and may be
> distributed or copied, unless specifically noted otherwise.

The CO-OPS disclaimers concern the quality of raw and forecast data and external links;
they state no licence. The API documentation asks clients to limit their request rate
(throttling) and the length of each request; those are access terms, not licence terms.
