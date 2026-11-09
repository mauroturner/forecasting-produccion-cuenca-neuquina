# Ablación con datos de fractura

Se corrió el machine learning sin y con variables de fractura sobre los mismos pares: 4.937 pozos, 24 orígenes de evaluación, 506.386 pares evaluados por modelo.

**Regla fijada de antemano.** Los datos de fractura se suman al modelo base solo si la pinball escalada del machine learning con ellos es menor, por al menos 2 % relativo, en al menos 3 de cada 4 celdas (fluido, horizonte y segmento) y no empeora más de 2 % en ninguna.

**Resultado.** Mejoran 0 de 16 celdas (hacían falta 12) y ninguna empeora más de 2 %; el cambio medio de la pinball escalada es 0,7 %. Los datos de fractura no se suman al modelo base.

| Fluido | Horizonte | Series | Pares | WAPE sin | WAPE con | Pinball sin | Pinball con | Cambio | Cobertura sin | Cobertura con | Pozos donde mejora |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Gas | 1 | elegibles | 77.157 | 27,2 % | 27,3 % | 0,2713 | 0,2717 | 0,2 % | 78,2 % | 78,3 % | 50,1 % |
| Gas | 1 | jóvenes | 8.505 | 24,2 % | 24,3 % | 0,2413 | 0,2430 | 0,7 % | 77,7 % | 77,5 % | 48,3 % |
| Gas | 3 | elegibles | 69.889 | 35,3 % | 35,5 % | 0,3495 | 0,3505 | 0,3 % | 78,1 % | 78,2 % | 46,9 % |
| Gas | 3 | jóvenes | 7.714 | 38,3 % | 38,6 % | 0,3790 | 0,3846 | 1,5 % | 77,1 % | 77,0 % | 50,9 % |
| Gas | 6 | elegibles | 59.283 | 38,8 % | 38,7 % | 0,3826 | 0,3835 | 0,3 % | 78,8 % | 79,0 % | 49,8 % |
| Gas | 6 | jóvenes | 6.573 | 42,6 % | 42,7 % | 0,4241 | 0,4277 | 0,8 % | 78,5 % | 78,7 % | 46,5 % |
| Gas | 12 | elegibles | 39.319 | 46,7 % | 46,8 % | 0,4525 | 0,4534 | 0,2 % | 77,3 % | 77,7 % | 51,3 % |
| Gas | 12 | jóvenes | 4.415 | 50,9 % | 52,6 % | 0,5085 | 0,5185 | 2,0 % | 77,6 % | 77,8 % | 48,1 % |
| Petróleo | 1 | elegibles | 65.546 | 21,8 % | 21,9 % | 0,2258 | 0,2261 | 0,1 % | 78,9 % | 79,2 % | 49,7 % |
| Petróleo | 1 | jóvenes | 8.205 | 21,2 % | 21,2 % | 0,2136 | 0,2141 | 0,2 % | 75,9 % | 76,8 % | 50,5 % |
| Petróleo | 3 | elegibles | 59.275 | 33,2 % | 33,3 % | 0,3347 | 0,3347 | 0,0 % | 78,2 % | 78,1 % | 51,3 % |
| Petróleo | 3 | jóvenes | 7.160 | 32,9 % | 33,1 % | 0,3297 | 0,3325 | 0,9 % | 76,7 % | 75,9 % | 49,2 % |
| Petróleo | 6 | elegibles | 50.098 | 37,6 % | 37,7 % | 0,3730 | 0,3734 | 0,1 % | 78,5 % | 78,5 % | 51,3 % |
| Petróleo | 6 | jóvenes | 6.164 | 41,3 % | 41,9 % | 0,4104 | 0,4175 | 1,7 % | 76,5 % | 76,6 % | 47,5 % |
| Petróleo | 12 | elegibles | 32.919 | 42,2 % | 42,2 % | 0,4165 | 0,4169 | 0,1 % | 77,9 % | 77,6 % | 50,4 % |
| Petróleo | 12 | jóvenes | 4.164 | 46,1 % | 46,9 % | 0,4596 | 0,4666 | 1,5 % | 74,4 % | 73,8 % | 48,5 % |
