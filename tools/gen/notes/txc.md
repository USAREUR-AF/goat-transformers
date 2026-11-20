## TransXChange documents

A TransXChange document has one root, `TransXChange`, whose sections (serviced
organisations, NPTG localities, stop points, stop areas, route sections, routes, journey
pattern sections, operators, services, vehicle journeys, registrations, supporting
documents) are lists in the one document; they are not exchanged as documents of their own.
This pack reads the whole document, walked to ten element steps and three levels of
repeated elements (the caps of the NeTEx packs).

The schema's NaPTAN and NPTG files are chameleon includes: they have no targetNamespace and
take the TransXChange namespace, so a document writes their elements under the same default
namespace as the rest, without a prefix.

## Positions are not bound

A stop point's `Place/Location` is a choice of three forms: Ordnance Survey grid
coordinates (`Easting`, `Northing`), WGS 84 coordinates (`Longitude`, `Latitude`, decimal
degrees, as the schema's `WgsGroup` states), or both inside `Translation`. The generator
maps a choice only when every branch is one simple leaf, so the location is not mapped
(counted under "choice with a branch that is not a simple leaf"). Mapping the WGS 84 branch
needs either a pack-language way to read whichever of two locators is present, or a
generator that maps each branch of such a choice; `lat` and `lon` are therefore not bound.
A single stop point is not a message of its own, so no single-entity pack is generated.

## Not read: the govtalk address and personal-details namespaces

Operator, garage and contact addresses, telephone numbers and names are typed from the
govtalk.gov.uk address and personal-details schemas (`apd/`), each in a namespace of its
own; an instance writes those elements with a prefix, which the xml wire does not read.
The namespaces are declined and their places are listed below.
