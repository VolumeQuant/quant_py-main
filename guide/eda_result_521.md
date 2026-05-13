# 정답데이터 전수 EDA 결과 (1262건)

실행일: 2026-05-06
정답데이터1: 54건 / 정답데이터2: 1208건

---

## 1. 채널 × 도메인

| 채널 \ 도메인 | credit_loan | derivatives | marketing | misc | pension | process | product | settlement | (합계) |
|---|---|---|---|---|---|---|---|---|---|
| LMS_고지 | 111 | 233 | 7 | 114 | 57 | 163 | 273 | 220 | **1178** |
| LMS_마케팅 | 0 | 0 | 0 | 0 | 0 | 0 | 9 | 0 | **9** |
| SMS | 6 | 1 | 0 | 37 | 1 | 10 | 17 | 3 | **75** |
| **(합계)** | **117** | **234** | **7** | **151** | **58** | **173** | **299** | **223** | **1262** |

---

## 2. 도메인 × 라벨

| 도메인 \ 라벨 | HIGH | LOW | MEDIUM | NEGATIVE | (합계) |
|---|---|---|---|---|---|
| credit_loan | 55 | 45 | 16 | 1 | **117** |
| derivatives | 134 | 91 | 9 | 0 | **234** |
| marketing | 4 | 0 | 3 | 0 | **7** |
| misc | 78 | 13 | 57 | 3 | **151** |
| pension | 0 | 0 | 58 | 0 | **58** |
| process | 122 | 9 | 42 | 0 | **173** |
| product | 178 | 41 | 80 | 0 | **299** |
| settlement | 123 | 46 | 50 | 4 | **223** |
| **(합계)** | **694** | **245** | **315** | **8** | **1262** |

---

## 3. 패턴 빈도 (가이드 backing 명확)

| 패턴 코드 | 빈도 | 빈도 % | 가이드 페이지 |
|---|---|---|---|
| VAR.NAME | 1089 | 86.3% | 78-79p |
| OPN.HONOR.A | 1062 | 84.2% | 36p, 60p |
| VAR.ACCT | 854 | 67.7% | 78-79p |
| ITM.DASH | 741 | 58.7% | 60p |
| BLK.QA.문의 | 591 | 46.8% | 60p |
| CLS.REQ | 590 | 46.8% | 26p |
| SYM.PHONE_DROP | 538 | 42.6% | 79p (☎ 삭제) |
| KOR.HANJA | 456 | 36.1% | 134p |
| BLK.UI.꼭확인 | 368 | 29.2% | 60p |
| CLS.ANN | 213 | 16.9% | 26p |
| VAR.DATE | 207 | 16.4% | 82-117p |
| TM.HHMM | 165 | 13.1% | 82-117p |
| VAR.URL | 145 | 11.5% | 79p |
| BLK.NAE | 143 | 11.3% | 60p |
| HDR.LMS.MAS | 42 | 3.3% | 60p |
| MAR.AD_TAG | 6 | 0.5% | 63-64p |
| MAR.SUSPENSE_3 | 6 | 0.5% | 63-64p |
| VOC.OPEN | 1 | 0.1% | 121-125p |

---

## 4. 50건 표본 누락 패턴 (전수에만 등장)

- MAR.AD_TAG (가이드 63-64p) — 50건 표본 누락, 전수 등장
- MAR.SUSPENSE_3 (가이드 63-64p) — 50건 표본 누락, 전수 등장
- VOC.OPEN (가이드 121-125p) — 50건 표본 누락, 전수 등장

---

## 4-1. HIGH 라벨 케이스 (시스템 프롬프트 EX 안전 후보)

총 694건. 회사 검수 통과 = '그대로 복사' 안전.

| 케이스 idx | 채널 | 도메인 | 패턴 수 |
|---|---|---|---|
| 59 | LMS_고지 | credit_loan | 10 |
| 61 | LMS_고지 | settlement | 7 |
| 73 | LMS_고지 | product | 6 |
| 75 | LMS_고지 | settlement | 7 |
| 76 | LMS_고지 | misc | 1 |
| 82 | LMS_고지 | credit_loan | 3 |
| 84 | LMS_고지 | misc | 5 |
| 85 | LMS_고지 | misc | 4 |
| 86 | LMS_고지 | credit_loan | 3 |
| 88 | LMS_고지 | credit_loan | 7 |
| 89 | LMS_고지 | credit_loan | 7 |
| 90 | LMS_고지 | misc | 2 |
| 93 | LMS_고지 | settlement | 5 |
| 95 | LMS_고지 | process | 4 |
| 96 | LMS_고지 | misc | 5 |
| 97 | LMS_고지 | process | 7 |
| 98 | LMS_고지 | process | 5 |
| 102 | LMS_고지 | credit_loan | 5 |
| 103 | LMS_고지 | credit_loan | 6 |
| 107 | LMS_고지 | credit_loan | 4 |
| 111 | LMS_고지 | credit_loan | 4 |
| 112 | LMS_고지 | credit_loan | 4 |
| 113 | LMS_고지 | process | 4 |
| 114 | LMS_고지 | credit_loan | 4 |
| 115 | LMS_고지 | process | 3 |
| 116 | LMS_고지 | process | 4 |
| 117 | LMS_고지 | product | 2 |
| 118 | LMS_고지 | process | 3 |
| 119 | LMS_고지 | process | 3 |
| 120 | LMS_고지 | process | 3 |
| 121 | LMS_고지 | derivatives | 4 |
| 122 | LMS_고지 | process | 5 |
| 124 | LMS_고지 | process | 10 |
| 125 | LMS_고지 | derivatives | 5 |
| 126 | LMS_고지 | process | 10 |
| 128 | LMS_고지 | process | 10 |
| 129 | LMS_고지 | process | 10 |
| 130 | LMS_고지 | misc | 3 |
| 131 | LMS_고지 | misc | 2 |
| 132 | LMS_고지 | derivatives | 4 |
| 135 | LMS_고지 | settlement | 8 |
| 136 | LMS_고지 | settlement | 8 |
| 137 | LMS_고지 | settlement | 8 |
| 141 | LMS_고지 | product | 2 |
| 142 | LMS_고지 | product | 3 |
| 143 | LMS_고지 | settlement | 6 |
| 144 | LMS_고지 | credit_loan | 6 |
| 145 | LMS_고지 | settlement | 6 |
| 146 | LMS_고지 | settlement | 5 |
| 147 | LMS_고지 | process | 10 |
| 148 | LMS_고지 | product | 6 |
| 149 | LMS_고지 | settlement | 6 |
| 150 | LMS_고지 | settlement | 4 |
| 151 | LMS_고지 | settlement | 5 |
| 152 | LMS_고지 | settlement | 4 |
| 153 | LMS_고지 | product | 4 |
| 154 | LMS_고지 | settlement | 6 |
| 155 | LMS_고지 | credit_loan | 6 |
| 156 | LMS_고지 | process | 7 |
| 157 | LMS_고지 | settlement | 8 |
| 158 | LMS_고지 | settlement | 8 |
| 159 | LMS_고지 | settlement | 9 |
| 160 | LMS_고지 | settlement | 4 |
| 162 | LMS_고지 | settlement | 5 |
| 163 | LMS_고지 | process | 6 |
| 164 | LMS_고지 | process | 7 |
| 165 | LMS_고지 | settlement | 7 |
| 166 | LMS_고지 | settlement | 10 |
| 167 | LMS_고지 | derivatives | 10 |
| 168 | LMS_고지 | derivatives | 10 |
| 169 | LMS_고지 | derivatives | 10 |
| 170 | LMS_고지 | derivatives | 10 |
| 177 | LMS_고지 | process | 4 |
| 178 | LMS_고지 | process | 4 |
| 179 | LMS_고지 | misc | 2 |
| 180 | LMS_고지 | process | 3 |
| 181 | LMS_고지 | process | 6 |
| 182 | LMS_고지 | process | 4 |
| 183 | LMS_고지 | process | 4 |
| 184 | LMS_고지 | process | 8 |
| 185 | LMS_고지 | settlement | 8 |
| 186 | LMS_고지 | process | 6 |
| 196 | LMS_고지 | product | 4 |
| 197 | LMS_고지 | product | 3 |
| 198 | LMS_고지 | product | 10 |
| 199 | LMS_고지 | process | 6 |
| 200 | LMS_고지 | credit_loan | 11 |
| 203 | LMS_고지 | product | 8 |
| 204 | LMS_고지 | product | 9 |
| 205 | LMS_고지 | product | 0 |
| 206 | LMS_고지 | product | 8 |
| 207 | LMS_마케팅 | product | 6 |
| 208 | LMS_고지 | product | 5 |
| 209 | LMS_고지 | product | 8 |
| 210 | LMS_고지 | product | 6 |
| 211 | LMS_고지 | product | 8 |
| 212 | LMS_고지 | product | 9 |
| 214 | LMS_고지 | product | 8 |
| 216 | LMS_고지 | product | 5 |
| 217 | LMS_고지 | product | 8 |
| 218 | LMS_고지 | product | 9 |
| 219 | LMS_고지 | product | 7 |
| 220 | LMS_고지 | product | 7 |
| 221 | LMS_고지 | product | 7 |
| 222 | LMS_고지 | product | 6 |
| 223 | LMS_고지 | product | 5 |
| 230 | LMS_고지 | settlement | 6 |
| 231 | LMS_고지 | product | 7 |
| 232 | LMS_고지 | product | 7 |
| 235 | LMS_마케팅 | product | 9 |
| 236 | LMS_고지 | product | 6 |
| 237 | LMS_고지 | product | 9 |
| 238 | LMS_고지 | product | 5 |
| 239 | LMS_고지 | product | 2 |
| 248 | LMS_고지 | derivatives | 4 |
| 249 | LMS_고지 | derivatives | 6 |
| 257 | LMS_고지 | derivatives | 4 |
| 264 | LMS_고지 | process | 5 |
| 269 | LMS_고지 | product | 5 |
| 270 | LMS_고지 | product | 8 |
| 276 | LMS_고지 | credit_loan | 4 |
| 281 | LMS_고지 | derivatives | 4 |
| 282 | LMS_고지 | derivatives | 4 |
| 283 | LMS_고지 | derivatives | 4 |
| 284 | LMS_고지 | derivatives | 4 |
| 285 | LMS_고지 | derivatives | 4 |
| 287 | LMS_고지 | settlement | 4 |
| 292 | LMS_고지 | process | 5 |
| 293 | LMS_고지 | derivatives | 7 |
| 294 | LMS_고지 | derivatives | 4 |
| 295 | LMS_고지 | derivatives | 4 |
| 297 | LMS_고지 | derivatives | 7 |
| 298 | LMS_고지 | derivatives | 11 |
| 299 | LMS_고지 | derivatives | 4 |
| 300 | LMS_고지 | derivatives | 4 |
| 301 | LMS_고지 | derivatives | 4 |
| 302 | LMS_고지 | derivatives | 4 |
| 303 | LMS_고지 | derivatives | 4 |
| 304 | LMS_고지 | derivatives | 4 |
| 306 | LMS_고지 | derivatives | 4 |
| 307 | LMS_고지 | derivatives | 4 |
| 308 | LMS_고지 | derivatives | 4 |
| 309 | LMS_고지 | derivatives | 4 |
| 310 | LMS_고지 | derivatives | 4 |
| 311 | LMS_고지 | derivatives | 4 |
| 312 | LMS_고지 | settlement | 4 |
| 315 | LMS_고지 | process | 4 |
| 316 | LMS_고지 | derivatives | 5 |
| 317 | LMS_고지 | derivatives | 5 |
| 318 | LMS_고지 | derivatives | 5 |
| 319 | LMS_고지 | derivatives | 6 |
| 321 | LMS_고지 | settlement | 5 |
| 324 | LMS_고지 | derivatives | 7 |
| 325 | LMS_고지 | derivatives | 6 |
| 329 | LMS_고지 | derivatives | 5 |
| 330 | LMS_고지 | derivatives | 2 |
| 331 | LMS_고지 | derivatives | 2 |
| 334 | LMS_고지 | credit_loan | 7 |
| 337 | LMS_고지 | process | 6 |
| 338 | LMS_고지 | process | 5 |
| 339 | LMS_고지 | process | 5 |
| 340 | LMS_고지 | process | 5 |
| 343 | LMS_고지 | process | 6 |
| 344 | SMS | product | 3 |
| 345 | LMS_고지 | process | 7 |
| 370 | LMS_고지 | process | 8 |
| 371 | LMS_고지 | process | 3 |
| 372 | LMS_고지 | process | 2 |
| 373 | LMS_고지 | process | 2 |
| 374 | LMS_고지 | settlement | 4 |
| 376 | LMS_고지 | process | 4 |
| 377 | LMS_고지 | process | 5 |
| 380 | LMS_고지 | settlement | 5 |
| 381 | LMS_고지 | process | 4 |
| 382 | LMS_고지 | misc | 6 |
| 385 | LMS_고지 | settlement | 6 |
| 387 | LMS_고지 | process | 4 |
| 388 | LMS_고지 | process | 3 |
| 391 | LMS_고지 | misc | 5 |
| 392 | LMS_고지 | process | 4 |
| 393 | LMS_고지 | settlement | 5 |
| 394 | LMS_고지 | settlement | 5 |
| 395 | LMS_고지 | settlement | 8 |
| 396 | LMS_고지 | process | 5 |
| 397 | LMS_고지 | process | 5 |
| 398 | LMS_고지 | settlement | 7 |
| 399 | LMS_고지 | settlement | 4 |
| 400 | LMS_마케팅 | product | 9 |
| 402 | LMS_고지 | derivatives | 9 |
| 403 | LMS_고지 | misc | 8 |
| 404 | LMS_고지 | marketing | 8 |
| 405 | LMS_고지 | misc | 6 |
| 406 | LMS_고지 | misc | 9 |
| 407 | LMS_고지 | misc | 9 |
| 408 | LMS_고지 | credit_loan | 6 |
| 409 | LMS_고지 | settlement | 6 |
| 411 | LMS_고지 | marketing | 4 |
| 412 | LMS_고지 | credit_loan | 7 |
| 413 | LMS_고지 | credit_loan | 6 |
| 415 | LMS_고지 | process | 4 |
| 416 | LMS_고지 | process | 3 |
| 417 | LMS_고지 | process | 3 |
| 418 | LMS_고지 | product | 8 |
| 419 | LMS_고지 | process | 1 |
| 420 | LMS_고지 | product | 10 |
| 421 | LMS_고지 | product | 9 |
| 422 | LMS_고지 | product | 8 |
| 423 | LMS_고지 | process | 1 |
| 424 | LMS_고지 | product | 6 |
| 425 | LMS_고지 | process | 5 |
| 426 | LMS_고지 | misc | 3 |
| 427 | LMS_고지 | misc | 4 |
| 428 | LMS_고지 | misc | 6 |
| 429 | LMS_고지 | misc | 5 |
| 430 | LMS_고지 | misc | 5 |
| 431 | LMS_고지 | misc | 5 |
| 432 | LMS_고지 | misc | 5 |
| 433 | LMS_고지 | credit_loan | 4 |
| 434 | LMS_고지 | misc | 4 |
| 435 | LMS_고지 | product | 9 |
| 436 | LMS_고지 | product | 9 |
| 437 | LMS_고지 | product | 7 |
| 438 | LMS_고지 | credit_loan | 9 |
| 439 | LMS_고지 | product | 8 |
| 440 | LMS_고지 | product | 6 |
| 441 | LMS_고지 | product | 5 |
| 442 | LMS_고지 | product | 5 |
| 443 | LMS_고지 | product | 3 |
| 444 | LMS_고지 | product | 3 |
| 445 | LMS_고지 | product | 3 |
| 446 | LMS_고지 | product | 3 |
| 447 | LMS_고지 | product | 7 |
| 469 | LMS_고지 | product | 9 |
| 470 | LMS_고지 | product | 8 |
| 596 | LMS_고지 | product | 6 |
| 598 | LMS_고지 | misc | 2 |
| 601 | LMS_고지 | credit_loan | 5 |
| 602 | LMS_고지 | misc | 6 |
| 603 | LMS_고지 | misc | 4 |
| 605 | LMS_고지 | credit_loan | 5 |
| 606 | LMS_고지 | credit_loan | 7 |
| 607 | LMS_고지 | credit_loan | 7 |
| 608 | LMS_고지 | misc | 2 |
| 610 | LMS_고지 | settlement | 4 |
| 611 | LMS_고지 | process | 4 |
| 612 | LMS_고지 | misc | 5 |
| 613 | LMS_고지 | process | 5 |
| 615 | LMS_고지 | credit_loan | 6 |
| 616 | LMS_고지 | credit_loan | 6 |
| 619 | LMS_고지 | credit_loan | 3 |
| 620 | SMS | credit_loan | 4 |
| 621 | SMS | credit_loan | 4 |
| 622 | LMS_고지 | settlement | 9 |
| 623 | LMS_고지 | credit_loan | 10 |
| 624 | LMS_고지 | process | 7 |
| 625 | SMS | credit_loan | 4 |
| 626 | SMS | product | 3 |
| 627 | LMS_고지 | process | 2 |
| 628 | LMS_고지 | product | 2 |
| 629 | LMS_고지 | derivatives | 3 |
| 630 | LMS_고지 | product | 3 |
| 631 | LMS_고지 | process | 3 |
| 632 | LMS_고지 | process | 3 |
| 633 | LMS_고지 | process | 6 |
| 634 | LMS_고지 | process | 8 |
| 635 | LMS_고지 | derivatives | 5 |
| 636 | LMS_고지 | process | 12 |
| 637 | LMS_고지 | process | 11 |
| 638 | LMS_고지 | misc | 3 |
| 639 | LMS_고지 | misc | 2 |
| 640 | LMS_고지 | derivatives | 4 |
| 642 | LMS_고지 | settlement | 8 |
| 643 | LMS_고지 | settlement | 8 |
| 644 | LMS_고지 | settlement | 8 |
| 647 | LMS_고지 | product | 3 |
| 648 | LMS_고지 | product | 3 |
| 649 | LMS_고지 | process | 9 |
| 650 | LMS_고지 | process | 2 |
| 651 | LMS_고지 | process | 4 |
| 652 | LMS_고지 | process | 2 |
| 653 | LMS_고지 | settlement | 5 |
| 656 | LMS_고지 | process | 4 |
| 657 | LMS_고지 | process | 3 |
| 658 | LMS_고지 | settlement | 5 |
| 662 | LMS_고지 | misc | 3 |
| 664 | LMS_고지 | process | 3 |
| 665 | LMS_고지 | settlement | 4 |
| 666 | LMS_고지 | settlement | 4 |
| 669 | LMS_고지 | settlement | 5 |
| 670 | LMS_고지 | settlement | 3 |
| 671 | LMS_고지 | process | 3 |
| 672 | LMS_고지 | settlement | 5 |
| 673 | LMS_고지 | process | 3 |
| 674 | LMS_고지 | misc | 4 |
| 675 | LMS_고지 | misc | 4 |
| 676 | LMS_고지 | settlement | 5 |
| 677 | LMS_고지 | settlement | 7 |
| 678 | LMS_고지 | misc | 5 |
| 679 | LMS_고지 | misc | 5 |
| 680 | LMS_고지 | settlement | 5 |
| 681 | LMS_고지 | settlement | 6 |
| 682 | LMS_고지 | settlement | 4 |
| 683 | LMS_마케팅 | product | 9 |
| 684 | LMS_마케팅 | product | 9 |
| 685 | LMS_고지 | derivatives | 9 |
| 686 | LMS_고지 | product | 11 |
| 687 | LMS_고지 | product | 11 |
| 688 | LMS_고지 | product | 0 |
| 689 | LMS_고지 | product | 9 |
| 690 | LMS_고지 | product | 7 |
| 691 | LMS_고지 | product | 8 |
| 692 | LMS_고지 | product | 6 |
| 693 | LMS_고지 | product | 9 |
| 695 | LMS_고지 | product | 5 |
| 696 | LMS_고지 | product | 9 |
| 697 | LMS_고지 | product | 8 |
| 698 | LMS_고지 | product | 9 |
| 699 | LMS_고지 | product | 9 |
| 700 | LMS_고지 | product | 7 |
| 701 | LMS_고지 | product | 7 |
| 702 | LMS_고지 | product | 7 |
| 703 | LMS_고지 | product | 5 |
| 704 | LMS_고지 | product | 6 |
| 708 | LMS_고지 | settlement | 7 |
| 709 | LMS_고지 | product | 7 |
| 710 | LMS_고지 | product | 9 |
| 711 | LMS_고지 | product | 8 |
| 712 | LMS_고지 | product | 9 |
| 713 | LMS_고지 | product | 5 |
| 714 | LMS_고지 | product | 8 |
| 715 | LMS_고지 | product | 5 |
| 716 | LMS_고지 | product | 2 |
| 723 | LMS_고지 | derivatives | 5 |
| 724 | LMS_고지 | derivatives | 7 |
| 727 | LMS_고지 | derivatives | 6 |
| 730 | LMS_고지 | derivatives | 5 |
| 739 | LMS_고지 | settlement | 4 |
| 740 | LMS_고지 | credit_loan | 5 |
| 741 | LMS_고지 | settlement | 7 |
| 742 | LMS_고지 | settlement | 5 |
| 743 | LMS_고지 | process | 10 |
| 744 | LMS_고지 | product | 7 |
| 745 | LMS_고지 | settlement | 6 |
| 746 | LMS_고지 | settlement | 4 |
| 747 | LMS_고지 | settlement | 6 |
| 748 | LMS_고지 | settlement | 4 |
| 749 | LMS_고지 | settlement | 4 |
| 750 | LMS_고지 | settlement | 7 |
| 751 | LMS_고지 | settlement | 7 |
| 752 | LMS_고지 | credit_loan | 6 |
| 753 | LMS_고지 | settlement | 7 |
| 754 | LMS_고지 | settlement | 8 |
| 755 | LMS_고지 | settlement | 8 |
| 756 | LMS_고지 | settlement | 8 |
| 757 | LMS_고지 | process | 4 |
| 759 | LMS_고지 | misc | 8 |
| 760 | LMS_고지 | misc | 8 |
| 761 | LMS_고지 | misc | 6 |
| 762 | LMS_고지 | misc | 9 |
| 763 | LMS_고지 | misc | 8 |
| 764 | LMS_고지 | settlement | 6 |
| 765 | LMS_고지 | settlement | 5 |
| 767 | LMS_고지 | marketing | 5 |
| 769 | LMS_고지 | settlement | 6 |
| 771 | LMS_고지 | process | 2 |
| 772 | LMS_고지 | process | 3 |
| 773 | LMS_고지 | process | 3 |
| 774 | LMS_고지 | process | 3 |
| 775 | LMS_고지 | process | 4 |
| 776 | LMS_고지 | process | 4 |
| 777 | LMS_고지 | product | 5 |
| 781 | LMS_고지 | product | 5 |
| 782 | LMS_고지 | product | 8 |
| 787 | LMS_고지 | settlement | 7 |
| 788 | LMS_고지 | settlement | 6 |
| 789 | LMS_고지 | settlement | 6 |
| 790 | LMS_고지 | settlement | 6 |
| 791 | LMS_고지 | settlement | 6 |
| 792 | LMS_고지 | settlement | 9 |
| 793 | LMS_고지 | derivatives | 11 |
| 794 | LMS_고지 | derivatives | 11 |
| 795 | LMS_고지 | derivatives | 11 |
| 796 | LMS_고지 | derivatives | 11 |
| 798 | LMS_고지 | process | 5 |
| 800 | LMS_고지 | product | 10 |
| 803 | LMS_고지 | product | 6 |
| 805 | LMS_고지 | process | 1 |
| 806 | LMS_고지 | product | 5 |
| 807 | LMS_고지 | product | 9 |
| 808 | LMS_고지 | product | 9 |
| 809 | LMS_고지 | process | 3 |
| 810 | LMS_고지 | product | 6 |
| 811 | LMS_고지 | product | 3 |
| 815 | LMS_고지 | misc | 5 |
| 816 | LMS_고지 | process | 4 |
| 817 | LMS_고지 | misc | 3 |
| 818 | LMS_고지 | process | 3 |
| 819 | LMS_고지 | process | 6 |
| 820 | LMS_고지 | misc | 6 |
| 821 | LMS_고지 | misc | 4 |
| 828 | LMS_고지 | misc | 6 |
| 829 | LMS_고지 | misc | 6 |
| 832 | LMS_고지 | product | 2 |
| 833 | LMS_고지 | product | 3 |
| 834 | LMS_고지 | product | 10 |
| 835 | LMS_고지 | misc | 1 |
| 836 | LMS_고지 | misc | 1 |
| 837 | LMS_고지 | misc | 1 |
| 838 | LMS_고지 | misc | 1 |
| 839 | LMS_고지 | credit_loan | 3 |
| 844 | LMS_고지 | derivatives | 4 |
| 845 | LMS_고지 | derivatives | 4 |
| 846 | LMS_고지 | derivatives | 4 |
| 847 | LMS_고지 | derivatives | 4 |
| 848 | LMS_고지 | derivatives | 4 |
| 850 | LMS_고지 | settlement | 4 |
| 854 | LMS_고지 | derivatives | 5 |
| 855 | LMS_고지 | derivatives | 7 |
| 856 | LMS_고지 | derivatives | 4 |
| 857 | LMS_고지 | derivatives | 4 |
| 858 | LMS_고지 | derivatives | 7 |
| 859 | LMS_고지 | derivatives | 10 |
| 860 | LMS_고지 | derivatives | 4 |
| 861 | LMS_고지 | derivatives | 4 |
| 862 | LMS_고지 | derivatives | 4 |
| 863 | LMS_고지 | derivatives | 4 |
| 864 | LMS_고지 | derivatives | 4 |
| 865 | LMS_고지 | derivatives | 4 |
| 866 | LMS_고지 | derivatives | 4 |
| 867 | LMS_고지 | derivatives | 4 |
| 868 | LMS_고지 | derivatives | 3 |
| 869 | LMS_고지 | derivatives | 3 |
| 870 | LMS_고지 | derivatives | 4 |
| 871 | LMS_고지 | derivatives | 4 |
| 872 | LMS_고지 | settlement | 3 |
| 875 | LMS_고지 | derivatives | 2 |
| 876 | LMS_고지 | derivatives | 7 |
| 877 | LMS_고지 | derivatives | 5 |
| 878 | LMS_고지 | derivatives | 5 |
| 879 | LMS_고지 | derivatives | 7 |
| 881 | LMS_고지 | derivatives | 5 |
| 884 | LMS_고지 | derivatives | 7 |
| 885 | LMS_고지 | derivatives | 7 |
| 887 | LMS_고지 | derivatives | 5 |
| 888 | LMS_고지 | derivatives | 2 |
| 889 | LMS_고지 | derivatives | 2 |
| 890 | LMS_고지 | credit_loan | 5 |
| 891 | LMS_고지 | misc | 4 |
| 892 | SMS | product | 1 |
| 893 | LMS_고지 | settlement | 7 |
| 894 | LMS_고지 | product | 8 |
| 895 | LMS_고지 | product | 9 |
| 896 | LMS_고지 | product | 8 |
| 897 | LMS_고지 | credit_loan | 8 |
| 898 | LMS_고지 | product | 8 |
| 899 | LMS_고지 | product | 5 |
| 900 | LMS_고지 | product | 5 |
| 901 | LMS_고지 | product | 5 |
| 902 | LMS_고지 | product | 3 |
| 903 | LMS_고지 | product | 3 |
| 904 | LMS_고지 | product | 3 |
| 905 | LMS_고지 | product | 3 |
| 906 | LMS_고지 | process | 6 |
| 907 | LMS_고지 | credit_loan | 10 |
| 950 | LMS_고지 | product | 6 |
| 952 | LMS_고지 | misc | 2 |
| 955 | LMS_고지 | credit_loan | 5 |
| 956 | LMS_고지 | misc | 6 |
| 957 | LMS_고지 | misc | 4 |
| 959 | LMS_고지 | credit_loan | 5 |
| 960 | LMS_고지 | credit_loan | 7 |
| 961 | LMS_고지 | credit_loan | 7 |
| 962 | LMS_고지 | misc | 2 |
| 964 | LMS_고지 | settlement | 4 |
| 965 | LMS_고지 | process | 4 |
| 966 | LMS_고지 | misc | 5 |
| 967 | LMS_고지 | process | 5 |
| 969 | LMS_고지 | credit_loan | 6 |
| 970 | LMS_고지 | credit_loan | 6 |
| 973 | LMS_고지 | credit_loan | 3 |
| 974 | SMS | credit_loan | 4 |
| 975 | SMS | credit_loan | 4 |
| 976 | LMS_고지 | settlement | 9 |
| 977 | LMS_고지 | credit_loan | 10 |
| 978 | LMS_고지 | process | 7 |
| 979 | SMS | credit_loan | 4 |
| 980 | SMS | product | 3 |
| 981 | LMS_고지 | process | 2 |
| 982 | LMS_고지 | product | 2 |
| 983 | LMS_고지 | derivatives | 3 |
| 984 | LMS_고지 | product | 3 |
| 985 | LMS_고지 | process | 3 |
| 986 | LMS_고지 | process | 3 |
| 987 | LMS_고지 | process | 6 |
| 988 | LMS_고지 | process | 8 |
| 989 | LMS_고지 | derivatives | 5 |
| 990 | LMS_고지 | process | 12 |
| 991 | LMS_고지 | process | 11 |
| 992 | LMS_고지 | misc | 3 |
| 993 | LMS_고지 | misc | 2 |
| 994 | LMS_고지 | derivatives | 4 |
| 996 | LMS_고지 | settlement | 8 |
| 997 | LMS_고지 | settlement | 8 |
| 998 | LMS_고지 | settlement | 8 |
| 1001 | LMS_고지 | product | 3 |
| 1002 | LMS_고지 | product | 3 |
| 1003 | LMS_고지 | process | 9 |
| 1004 | LMS_고지 | process | 2 |
| 1005 | LMS_고지 | process | 4 |
| 1006 | LMS_고지 | process | 2 |
| 1007 | LMS_고지 | settlement | 5 |
| 1010 | LMS_고지 | process | 4 |
| 1011 | LMS_고지 | process | 3 |
| 1012 | LMS_고지 | settlement | 5 |
| 1016 | LMS_고지 | misc | 3 |
| 1018 | LMS_고지 | process | 3 |
| 1019 | LMS_고지 | settlement | 4 |
| 1020 | LMS_고지 | settlement | 4 |
| 1023 | LMS_고지 | settlement | 5 |
| 1024 | LMS_고지 | settlement | 3 |
| 1025 | LMS_고지 | process | 3 |
| 1026 | LMS_고지 | settlement | 5 |
| 1027 | LMS_고지 | process | 3 |
| 1028 | LMS_고지 | misc | 4 |
| 1029 | LMS_고지 | misc | 4 |
| 1030 | LMS_고지 | settlement | 5 |
| 1031 | LMS_고지 | settlement | 7 |
| 1032 | LMS_고지 | misc | 5 |
| 1033 | LMS_고지 | misc | 5 |
| 1034 | LMS_고지 | settlement | 5 |
| 1035 | LMS_고지 | settlement | 6 |
| 1036 | LMS_고지 | settlement | 4 |
| 1037 | LMS_마케팅 | product | 9 |
| 1038 | LMS_마케팅 | product | 9 |
| 1039 | LMS_고지 | derivatives | 9 |
| 1040 | LMS_고지 | product | 11 |
| 1041 | LMS_고지 | product | 11 |
| 1042 | LMS_고지 | product | 0 |
| 1043 | LMS_고지 | product | 9 |
| 1044 | LMS_고지 | product | 7 |
| 1045 | LMS_고지 | product | 8 |
| 1046 | LMS_고지 | product | 6 |
| 1047 | LMS_고지 | product | 9 |
| 1049 | LMS_고지 | product | 5 |
| 1050 | LMS_고지 | product | 9 |
| 1051 | LMS_고지 | product | 8 |
| 1052 | LMS_고지 | product | 9 |
| 1053 | LMS_고지 | product | 9 |
| 1054 | LMS_고지 | product | 7 |
| 1055 | LMS_고지 | product | 7 |
| 1056 | LMS_고지 | product | 7 |
| 1057 | LMS_고지 | product | 5 |
| 1058 | LMS_고지 | product | 6 |
| 1062 | LMS_고지 | settlement | 7 |
| 1063 | LMS_고지 | product | 7 |
| 1064 | LMS_고지 | product | 9 |
| 1065 | LMS_고지 | product | 8 |
| 1066 | LMS_고지 | product | 9 |
| 1067 | LMS_고지 | product | 5 |
| 1068 | LMS_고지 | product | 8 |
| 1069 | LMS_고지 | product | 5 |
| 1070 | LMS_고지 | product | 2 |
| 1077 | LMS_고지 | derivatives | 5 |
| 1078 | LMS_고지 | derivatives | 7 |
| 1081 | LMS_고지 | derivatives | 6 |
| 1084 | LMS_고지 | derivatives | 5 |
| 1093 | LMS_고지 | settlement | 4 |
| 1094 | LMS_고지 | credit_loan | 5 |
| 1095 | LMS_고지 | settlement | 7 |
| 1096 | LMS_고지 | settlement | 5 |
| 1097 | LMS_고지 | process | 10 |
| 1098 | LMS_고지 | product | 7 |
| 1099 | LMS_고지 | settlement | 6 |
| 1100 | LMS_고지 | settlement | 4 |
| 1101 | LMS_고지 | settlement | 6 |
| 1102 | LMS_고지 | settlement | 4 |
| 1103 | LMS_고지 | settlement | 4 |
| 1104 | LMS_고지 | settlement | 7 |
| 1105 | LMS_고지 | settlement | 7 |
| 1106 | LMS_고지 | credit_loan | 6 |
| 1107 | LMS_고지 | settlement | 7 |
| 1108 | LMS_고지 | settlement | 8 |
| 1109 | LMS_고지 | settlement | 8 |
| 1110 | LMS_고지 | settlement | 8 |
| 1111 | LMS_고지 | process | 4 |
| 1113 | LMS_고지 | misc | 8 |
| 1114 | LMS_고지 | misc | 8 |
| 1115 | LMS_고지 | misc | 6 |
| 1116 | LMS_고지 | misc | 9 |
| 1117 | LMS_고지 | misc | 8 |
| 1118 | LMS_고지 | settlement | 6 |
| 1119 | LMS_고지 | settlement | 5 |
| 1121 | LMS_고지 | marketing | 5 |
| 1123 | LMS_고지 | settlement | 6 |
| 1125 | LMS_고지 | process | 2 |
| 1126 | LMS_고지 | process | 3 |
| 1127 | LMS_고지 | process | 3 |
| 1128 | LMS_고지 | process | 3 |
| 1129 | LMS_고지 | process | 4 |
| 1130 | LMS_고지 | process | 4 |
| 1131 | LMS_고지 | product | 5 |
| 1135 | LMS_고지 | product | 5 |
| 1136 | LMS_고지 | product | 8 |
| 1141 | LMS_고지 | settlement | 7 |
| 1142 | LMS_고지 | settlement | 6 |
| 1143 | LMS_고지 | settlement | 6 |
| 1144 | LMS_고지 | settlement | 6 |
| 1145 | LMS_고지 | settlement | 6 |
| 1146 | LMS_고지 | settlement | 9 |
| 1147 | LMS_고지 | derivatives | 11 |
| 1148 | LMS_고지 | derivatives | 11 |
| 1149 | LMS_고지 | derivatives | 11 |
| 1150 | LMS_고지 | derivatives | 11 |
| 1152 | LMS_고지 | process | 5 |
| 1154 | LMS_고지 | product | 10 |
| 1157 | LMS_고지 | product | 6 |
| 1159 | LMS_고지 | process | 1 |
| 1160 | LMS_고지 | product | 5 |
| 1161 | LMS_고지 | product | 9 |
| 1162 | LMS_고지 | product | 9 |
| 1163 | LMS_고지 | process | 3 |
| 1164 | LMS_고지 | product | 6 |
| 1165 | LMS_고지 | product | 3 |
| 1169 | LMS_고지 | misc | 5 |
| 1170 | LMS_고지 | process | 4 |
| 1171 | LMS_고지 | misc | 3 |
| 1172 | LMS_고지 | process | 3 |
| 1173 | LMS_고지 | process | 6 |
| 1174 | LMS_고지 | misc | 6 |
| 1175 | LMS_고지 | misc | 4 |
| 1182 | LMS_고지 | misc | 6 |
| 1183 | LMS_고지 | misc | 6 |
| 1186 | LMS_고지 | product | 2 |
| 1187 | LMS_고지 | product | 3 |
| 1188 | LMS_고지 | product | 10 |
| 1189 | LMS_고지 | misc | 1 |
| 1190 | LMS_고지 | misc | 1 |
| 1191 | LMS_고지 | misc | 1 |
| 1192 | LMS_고지 | misc | 1 |
| 1193 | LMS_고지 | credit_loan | 3 |
| 1198 | LMS_고지 | derivatives | 4 |
| 1199 | LMS_고지 | derivatives | 4 |
| 1200 | LMS_고지 | derivatives | 4 |
| 1201 | LMS_고지 | derivatives | 4 |
| 1202 | LMS_고지 | derivatives | 4 |
| 1204 | LMS_고지 | settlement | 4 |
| 1208 | LMS_고지 | derivatives | 5 |
| 1209 | LMS_고지 | derivatives | 7 |
| 1210 | LMS_고지 | derivatives | 4 |
| 1211 | LMS_고지 | derivatives | 4 |
| 1212 | LMS_고지 | derivatives | 7 |
| 1213 | LMS_고지 | derivatives | 10 |
| 1214 | LMS_고지 | derivatives | 4 |
| 1215 | LMS_고지 | derivatives | 4 |
| 1216 | LMS_고지 | derivatives | 4 |
| 1217 | LMS_고지 | derivatives | 4 |
| 1218 | LMS_고지 | derivatives | 4 |
| 1219 | LMS_고지 | derivatives | 4 |
| 1220 | LMS_고지 | derivatives | 4 |
| 1221 | LMS_고지 | derivatives | 4 |
| 1222 | LMS_고지 | derivatives | 3 |
| 1223 | LMS_고지 | derivatives | 3 |
| 1224 | LMS_고지 | derivatives | 4 |
| 1225 | LMS_고지 | derivatives | 4 |
| 1226 | LMS_고지 | settlement | 3 |
| 1229 | LMS_고지 | derivatives | 2 |
| 1230 | LMS_고지 | derivatives | 7 |
| 1231 | LMS_고지 | derivatives | 5 |
| 1232 | LMS_고지 | derivatives | 5 |
| 1233 | LMS_고지 | derivatives | 7 |
| 1235 | LMS_고지 | derivatives | 5 |
| 1238 | LMS_고지 | derivatives | 7 |
| 1239 | LMS_고지 | derivatives | 7 |
| 1241 | LMS_고지 | derivatives | 5 |
| 1242 | LMS_고지 | derivatives | 2 |
| 1243 | LMS_고지 | derivatives | 2 |
| 1244 | LMS_고지 | credit_loan | 5 |
| 1245 | LMS_고지 | misc | 4 |
| 1246 | SMS | product | 1 |
| 1247 | LMS_고지 | settlement | 7 |
| 1248 | LMS_고지 | product | 8 |
| 1249 | LMS_고지 | product | 9 |
| 1250 | LMS_고지 | product | 8 |
| 1251 | LMS_고지 | credit_loan | 8 |
| 1252 | LMS_고지 | product | 8 |
| 1253 | LMS_고지 | product | 5 |
| 1254 | LMS_고지 | product | 5 |
| 1255 | LMS_고지 | product | 5 |
| 1256 | LMS_고지 | product | 3 |
| 1257 | LMS_고지 | product | 3 |
| 1258 | LMS_고지 | product | 3 |
| 1259 | LMS_고지 | product | 3 |
| 1260 | LMS_고지 | process | 6 |
| 1261 | LMS_고지 | credit_loan | 10 |

---

## 4-2. NEGATIVE 케이스 (가이드 룰 미수용 — 차단 학습용)

총 8건. 가이드 적용 자제, 원안 가깝게 유지.

| 케이스 idx | 채널 | 도메인 |
|---|---|---|
| 410 | LMS_고지 | credit_loan |
| 414 | LMS_고지 | misc |
| 766 | LMS_고지 | settlement |
| 768 | LMS_고지 | settlement |
| 770 | LMS_고지 | misc |
| 1120 | LMS_고지 | settlement |
| 1122 | LMS_고지 | settlement |
| 1124 | LMS_고지 | misc |

---

## 4-3. 재현율 추정 (가이드 backing 패턴 기반)

필수 (≥80%) 패턴이 전수에 정확히 등장하는 비율 = 시스템 프롬프트가 가이드 backing 패턴을 재현하는 정도.

**필수 패턴 (≥80%)**:
- VAR.NAME (가이드 78-79p) — 86.3%
- OPN.HONOR.A (가이드 36p, 60p) — 84.2%

재현율 추정: 시스템 프롬프트 v6.0/v11.0/v6.0이 위 2개 필수 패턴을 모두 anchor에 박고 있는지 검증 필요. (수동 검증 권장)

---

## 5. 등급 분류 (가이드 backing)

- 필수 (≥80%): VAR.NAME, OPN.HONOR.A
- 조건부 (30-80%): BLK.QA.문의, CLS.REQ, VAR.ACCT, KOR.HANJA, SYM.PHONE_DROP, ITM.DASH
- 선택 (<30%): BLK.NAE, BLK.UI.꼭확인, HDR.LMS.MAS, CLS.ANN, TM.HHMM, VAR.DATE, VAR.URL, MAR.AD_TAG, MAR.SUSPENSE_3, VOC.OPEN

---

## 6. 자체 발명 통계 (가이드 silent — 백로그)

아래 항목은 가이드 PDF에 명시 없음. 운영 검토용 참고만:

- 95% CI / 신뢰구간: guide_check_backlog.md EDA-BL-1
- KL divergence / entropy: EDA-BL-2
- BLEU / ROUGE / Levenshtein: EDA-BL-3
