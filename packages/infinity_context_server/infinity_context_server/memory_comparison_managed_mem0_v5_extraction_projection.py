"""Pure pinned Mem0 2.0.15 extraction request projection.

The additive extraction prompt and prompt-builder semantics are adapted from
mem0ai 2.0.15, Copyright Mem0, under the Apache License 2.0. No Mem0 package,
provider SDK, network client, or caller-supplied executable is imported here.
"""

# ruff: noqa: E501 - the reviewed upstream prompt is stored as one compressed pin.

from __future__ import annotations

import base64
import hashlib
import json
import zlib
from dataclasses import dataclass
from datetime import date
from typing import final

from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5SourceUnit,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import is_sha256

MEM0_V5_EXTRACTION_IMPLEMENTATION_DOMAIN = "infinity-context.mem0-2.0.15-extraction-request.v1"
MEM0_V5_EXTRACTION_MODEL = "gpt-5.6-sol"
MEM0_V5_EXTRACTION_MAX_TOKENS = 4096
MEM0_V5_EXTRACTION_SYSTEM_PROMPT_SHA256 = (
    "ad19187a37813ef77ee156e714c0650e6ec749e0264bdc07d499bc9b24115155"
)
_MAX_SOURCE_MESSAGES = 100
_MAX_SOURCE_CONTENT_BYTES = 131_072
_MAX_EXTRACTION_REQUEST_BYTES = 1_048_576

_COMPRESSED_ADDITIVE_EXTRACTION_PROMPT_B85 = b"c-p;v>uw`QvgUt1MVbSwq+U{%)E9fSI51>M-L09Hx>r(9&%kI5imW7AR<VjxRg{`DYhZuv11!!Ho+mlq7m=BjMN(?nbLJR^O_5c3iHMAQL~d>U&Ro5Jceb_lmvUi}%9_Mn*jZUE&DocxN=8jtng95||BkQcl^tcZ?HhZSrM4K^!LVEuDZVd9wyyD9W$Sra)Y&k%W{khBj*t}-Q)Q!R-;Bzl!Iz69H#1I>+1iY&a>gI-Y*i;shWGaj)>4_e#4zRDR`RXMYIA&gdSp0vlZ}^HhQ%u9nH}M=u@0DU>a4)zGkq)31*Qu;RNH(!;1ZIouxY%Sd?^bwW2}~otDB^;Gt5)(DPY`Abg@6azj<pGwXJ0Iq^>hOUo==jT_+QZ^?&4#{!f7A&SFsPq%I45;4F2Y@EqHUfaD)}Qs93a(0;*_nS8%zj@L#vZU-24RL-!-RG}8es23AF=Dw2^j`+tKXqu_jUCffD$+2M~(5(pDJ|2x0*z;0`z)bVpHnzYbgi1zL)?}k3-!o@VLBniOH)e>}l6kYJZ0bmAmesXQ1D)_ei#?dU#N!S<SZC6h)K01-CAlm(Kmca;cbQ<%e41KdyF*C$gP$>Z-eg$5Y07yv0#H0QZ33K^1u0{mfXr;Z+%u=8DayuRw-_!hXIVk$%d1#E0A`jTh^Caq<4w$%CV)V+T|n=5=KS)*$D3<>`klG7_c&CFzOAhrz#X6koSW`)v9V&O-Zl4GGc~;m<li$p#L%~a#&!i8JpoP8^f1wnB_8IpEn&Frts>!QYha!|>yYNNXGiA46UZ_m$v*Ib16>0&0Nl5x;4#!ch8A;yKLAvPQeS2Nwg4&OQwI9UMp+XN?+ykCpqW<XVlp-IG+&jauG2o(dp!pm8Uq<C^lv8Foh{sw4Y*G|n%Z<BfT=8yixVG{B$$;=Dn8REt6AtE;1%R<_%4}LR(Sv(P52znMAKB+aM1vPB@j4j^5qfFkm(VuJz;u8*gzOasvzAnukm$2;b4MORLRc{jeW3{WJX*W9Ku=6W8@F#b{)>aj@_H=^>r$9pVTb?Fw~!W+_L<JR|o?PH_8`0GJnS8Ce7;6LQY#&bjYr^3n~K9U%tQbltW7SQ!-iDh`EiX34a0^{N2HOr^ka(14w4h=Rib_?O}m(U~9?-oR0=@uE&eKw`&$fPWBP_4ya0K0^Ao18fV-(ew<<UH-r&z+|HkjZj16B#4=Hw?DVd|2fpEaZ;0MNJKywnF+fZ^O)^kGH9V&Yq*h}x3{l<}WJt*{%fZZeG<jIB7qc0j1F}t#R1`jUU=aG{3T8ko<BYP7Qej?Yz`%+iy8vqi+q1KIvlQwmzzX=b3JENOoWvF)eOfkH3xC9q(=rDTu`wLxte$$B0X5{=t;GUoJdt@hN+Nz=*<AmeW^)QK?&=EcxgeySRL4jcP6BUj`A;Uv0m^jQvT4~_CGWNZh;%y5$omBA;8An#;&6X=&)o0_{JW$C2S@~JAkYO-?GK(~0J6zc*==P9o-236_v(VCc-3v`><chV-D1N=9DmK1x>z7^Swo@|H1<yUx$YsxmmE|~OyDH-(biA@=w)f|$n+MAEX9$oFqzOdR?4sU_V#+e^bP*^d25T<#6<Y-`^$HK5nOk-P0Zw3amy9EjYmgL2&1bLt?ke0MKPI(Tm^B1#J=FP*PvDGSzeEY&Yn3R%M3AW0h#z2BN&|lIF#!c1-v`E1AA6zfuVF4v{X4&lp?e7H4eGV;V2Yb^){P>h=DFAoWmZMoJ`1+%zxwH1W`?{D3TXK1!&5X`J9hX0px-0o5eik7~g`_#~iDbE?}x<o|pFn5GTY8xvU;fOtMe_;4mlA8J8ocJX1(!Wkope=ck^W+MVF*9?@#kzv>r%&C<GOIO@_N3~H+Z&zXbmoS$;vGfL^2vJtC+<lX7*ldcYWLQJ~`62`2JNw%TP^W#SjBS;n+24^6Ux6Us<yuZ3RzPvdy$J7Gc@*TvL?*Y;Ry=7ONOd%nt?M#HFfHx#xz_8O2Gm=P&VVuRhdp2c2VfJoFjxw~i2*-6#C``al-UOn(bBOC`6mnLey5zNAr6IEqOTGAbeFI67VF6^OfrBM=(A?Uy<Ifp>A3|vCnfC>VS!glRGw(@}!Wg_dL0Qd}$Z9DcU@eeL*H{qgge+?YLd(hCRV(CRZoME=s20K~lQl%_Jpyvo?o_~Y6{V=O$xNso{AaFb4v%sJl}rk-XWT4bt?!drPxSNVzNE;<yrU+-rZ4OEOv!rL@Gb!pxs5c`s}+XdGI%ipZOY|z`HQf>l1f#X<19r=p0mIT=mYgC&v6TQKg5pjl&Vg#Fvl<m(T;+w))`>ll;tgz9LNw)#)tcd&j<T22Zt|ut71qPGPwU7hDna~jHW>ISnXA;R$!aW;zjQf2D+2ucki4)UD?(IhZt~MT|0HB-VzeqR%x>Ang95I|KFsd1yDI&-zuKY3IBU*Z}n+@ir~EIje;7$47_ZrugFKo@E&@navFfXQ3D1|{^+uPrfeBQm8aeza<2?KBKM>+lT;g!cXD-pbAEFC?kFZ@5XXn4BDZRHn+a1BrSO&Rp;kk5Z{wS!2LTQkHx;XcmwiLD%RrG3;*Rb($Z>w3EMXW_;-}bzMT{L7KpGv16K9|4hHkiVFnXs%@WG(kE#;&qW17#apb%q{{8RZuR>wyq5M;ERtY{A%*-S~+wK}TXPrb<n(Q#bJ(VC0xpPTan@&{*|hLyJrXinXTP0WRjOBe{4QXUa?V(k%fQTZ89Hs$QEJOR~0brC*EqzzI#rhmm$VtegOvkBCqM)hNG$6Xm<Y;8*R{8tRXH;+>xw}?Xz6B;X}(>49`+?9C)0eJTA{PIlA>rWIxSe;XCx3=5|IlG(v5h6T?G@T#y<A9A6w`N$CNeWAEYwOvw*L-mi+t5ePo?%D9igto*vmM>h%==<Ls1A)6o!W%4-ohwurr+M%Jg2`UHmIlNaH#TgRyxEA%4sm4IpO1NRKR`+6BefItW0fAe^*{s_$#@Ec2sA7w?xJHlMHij$Qwc4HEhAwe04U5SL$axz|d-*JrfeXSJh8IR`Wf24n~Wasstk-89P{{vZ<tk?wRuwj#$zUN7EZO+^QME+PUSc*p#RaNwG9ah9aILG`F4}vW{DbO7Gy~_~!N1`wP`y+)jva8!a`Z2^PtBsJw~j2Grr~Y-p+C03xrmim)LZX0QiwGzxcsx5xa+P@x_`vDxmMZJ~4Qq=E*+zdc_zKbJf<_{ugTjv5>t<FZV#VQ{$IS$Ox;Qak{2Ix!088Zg_C7X`T{b%Yt{RCVY);oCLdyN8u&g^IBH1Zpl0I5ykV+q<0byr}0{)mkegF~@fllL?J8J_E?q7=un9as_Tiz7W??UzP`2fb7KqNyVn$3x{X@oS7Yw&_XE_TPy$ufCDP_uAZ&OJwBjvXajP%Ff67l)Qd%*FF%oaW*}-3`-ca8L!u9O(_Ub)$y3Bvy@$x`IEPux1S40Hcp=t&NYK7$Mt1ZXIa8}{xQ>EMY<LaXQRZ;z^hO*K9O$Zc=ZzwS{?38>zUz_b%N~0H2R(5eiU+u|o|+Oa*88hvK2edTHmk&El4s*q@4CRR$&ooXLf4bBadsXKty|!aShihKD?4jXBZdn8@R%_R?TTJb+po$d;yPP*s`Xnwm#Q&uJtRD6*4$dk^*7L;@BpXI3l%kFkmB+Im-L1s9aMS<f(Ogn26d99E%Vq`*V27irRpr_^WGOy<5W1;N7g!%WCSu6VwzvJtF%y8g%h>hOw@vs%+?u!VP0ZdJQ<fIR8gR!2I_LVzG*?ZcNj}RgO&=WGRK#vg1~OLLU{>|D6w<+AhZ`1)QiR$XEC?s5bFM1^DY{m3R*<K;u!B)2&Fr9H+G$T!DLr8urw3r76ihFvS+A!!db*#z)sR~F>C>~hcj_(>KqzKBdATGHz^Rj6JiVvRus@tS@Ri?Lg4}vBzkZ-#cS7>;}t=mnGVhbbiw`O-IQU53R`KdECHPuB0rZyqe`GHYDO_&j!o4v49aV!(GP|YsD~ys#g)^*j`7O1K>Dn8@k8H^Pq?$7=eCK}h0!$2(<$UgWDAZLMZxHf9i<=^$7KT6V|9QuOa%5YOf$j>=s66KAm%jl&k3~ft^=<^sqfrkBi#yBi`*}@V#ug*rryPSSowEJz7TCq=uKq|J*~FEe|f6=w1~rQoJ+y^qOgRd5?4>+b_Y#Y;)Q+3l?ae!>=Nkm050gm$E!0)qdEQtrS0_IX5wVNR-Jo-S>^8=Ap5rdrsu*nf45Z`GcvEx6&{nG_no^H;epr6$Z%B6AILnfoRSs%Wy)jfTRIB7dz(js8eA=GTE6W&hU$;Dg47-E+MHjWKwZAPIeuq8oLybNzr=^v$0s+}#xc|+#2AFufh#@ogobc+JP^l}5;eu#?9NqkMAM>oz75L;0^^PbFf_!etty)907~ionzN;uBo$zwLBL`u(Zz%suIR~49KrlS?M)9o;Z$lH!V0>t*Je=v9Dt!y^o*>^#7dXh=7GK>Q^1*nn!8Pj@yANMCFX5X6v<SUHUcYPh$E;S;HJ>;z%fMQcz9`kA_@l{@25<N&HqHh^0O}anCc`T4P}cXkawqaWzyH1W=YWxt8>6Im$n(_*%y6csk$>1#!agf#|p43)D=`dPJ6M0Y7B*+*6ejsCE!IsC5}~AG~RKoo+nO!PWM1+ZnL!Brt)q^Fz#!+I%mh<<wsZDK<1#j*qsM3@Ir%e*qGWRq&rQ(dgW^uVLNWmhw{G_k`iYSR#Vhasha;4Ue#kCr0@eYRXgSegi#XByS5$$J!7!WB*5}TBn5A*04+92(+tE^3kMVzbSDO(B1@&V53t0t+TqP>i8!_uzn{s%Vw2OWxM`eQ5SH#u%2p|pV0c)X5o~q6tKHx@mH*!!9%rCU71<BdvMJSgI-jZk(Xl_z&jKd{7WgpDmQj_7XCvsLKe^%Li6aTh^whD;XNR`-itM-bRGnlDk#fS_R<ZKt;hL);92<yj@xH9;@J51i)SX1xTV19q5$mgW#sn0%Or&Ec=OIRWMrV;IaLx`8etYbO6f&Y)Xl^LQC<brk2*w&&kd+=}I7NIm8x@SS>O*`}1E_B30Ik+hRt|r*qo%J8Skcj(sSwYo)*_63iwVFCqaj6LV#AUrq@nFPn@9#rNxvyRkiok2jor14$SY2|iUY`njQ%$u$o*ZDS%Ur7PKS!qe6A!9i6ZwH=Q|s1ov2%1Il=;}6_?8|cxr`35UDF@mlZf`E9lsZ0?@He!&<7Zy&f@~sFBoU;vI88Ch5^?6rgARk9h;-;^=|!z=v`^UwZR^!oIAiGMf7&zokk!f$>d#?zTd&o9MkRWQ{lIyk+(Y+1VV*sbyeUrG&WDVT3A&bjlgiexT$?+J(!n35>EmRq}{f{q;SSL-`0>611V;f;G(L6AkQYDbmcl3S3Omx$?2n_7|Ho)r=E5ZBl|jqX=8=Vq5oww>(6%k(4nYPf4+HtFqz%a66OJt%o!A%|W+q?it7`a}BJ>I_r@2)apy0K+Bp>(2wKHf<5M}l^Wyp)=-F<f|fwrBvdgo#=1ydRoW#H<?2{9SwfcI(nSt^y|)#Uivr(A?2~*}sx#`Ah+TQpd8<=u;^o}2Lib8-1*YT^z0N8qKa*RviSi7*|C;i(o_d*21?H1Y3tNNE9$j2k3>?3BO<C2Bz?D8>Y`1*iOVS>oEyVF6fgo2KWtTWtJM%YiLKsL(=nf6El&Ez{D(a2p5sj@d=Aje|6l>(aR`rCBs#!zM1%lw*LM&Cq1&BCSuS&fTSA=k)oN?6GPRLvbU;WkxdS0qKrR&!p#ceGXp$kaMfe0R7x{{nXr*+Xe0behKIWx@B$s@eN>-bL1ZSR_p#J)&|%`Cx3OLHeO(R)la;qEEeX`lBXF=_Pw@$Bpa!(C@9zG$Gm9;uUR!BYnu(lgr=k<)T9*iXz0k_m<`BTDigfvkJ-%pS(RXgBEm%n2xmQ@E|GD~zm<K9`?iW*0W_Nq}Qcxd|y|C5;7ekzub}Fh$~+!vYgoP9;$@nXs<8UEt93&w@A_+(QuED%pt|!>rO1pH;f0>5z_R`LxIOw2J}7<O|I|B4U*JF}fbYq{1bFyp=4UklwY|3u2AwxB}x7m!4^M4qgtv-&g!HJA!BGV1M7Gqfl`eNUD*Op1WHIgF~MAMh*SB#5H8;F6R4OUiCg0^(^~zN-UQz$dX%UJv8wo<YzFRUf=*Ib~Dg>y&G~hRcR!v<msEy5)9Fk8i$wOW-5|?J_%6S)`ej(DiJR}8!G%vHRDkU$prVz!MHs8)7h1&6JQz3vy#ai77nfr7GWjgpt?*O4^-`*E3lFbN~mI<MWM34lM_3%2{1aWEIFq;?l&&N2M+W`v<Hw!IO+Ba#eu{e`*aG&hd2ri#+h739X(AO$)skK48`S4!MrK-Yj$Ww#qrEt50a4^E{wq8#1Xe=dI#SdVdOm1;JM*%)oXeb)DkuK<akLeyUd{vnkl}z*_JRQb3>dDnCZpAE2y0i#$m4Z8#kNUbT2^2^0l8cj2|Kdrw;SP&!uFhN+u!mgsq&Iil-!U?mN*DEBwLSSfPa4TfahdF_pWN^h{LOn4k2$ULWZCZ;Mhq){-Elnw_fC8ncMblZ$MP{G#I}s`x4EHhrabNivJ-PI<qNqk0arqQiUBRo!OleWkZ@;{2jXtLwlRE-NKzf?U>kDQt?gdc)&W!<Z`<5P#rx9w{kvlcB}S`4Ulem)Y>wgzkNpz6gds2|u(^9RG7+p~nu(N*sRfyJ00-nf?({Q~ekIx70X=&uhhR&)>W~yS^Fx>G<8pvw+r2jZL+1$zo}@GT`GQ2|ioBO?%VKC*6UhF%<NKkh$-{#Q${smurp9wZtDISAAvoi7G|gXIMI==k<aIy|6yZ^m<-4;+wv}*xTw;q0DV<6#<%z<q{=60Y=k=Q8CqH7`c|jq3G>ic!-h^8cwD$I#E(1@V~DmkP9s>p>P-_MG}v)>F2(>iIbI~dYXUYoMFc}h>J=Llbb257^R~tP;<SyN!cIqBgdu=!;dj&QZL0!l))uMAh~0LfsN>a1_10XOromiJ92Ob-79K0@rK-!E(vS>QFj8w%9OJ%4+hqA+{WGMr$4J}&F<UUQbsgs8Br`M-B@aagugZMY{oK(M3Yz=2|}nuQs)2-%i72@n#@GztE2^Do0UGdvJL$JMH8l}w|idy(ZSgN$<Y7_F<~bawa1hp<(Uf+gTBPkduL&PlKeXmecB6d#;IgIEG5h>(|RvzS_<!yqyn=nCmkw`zjg!ZBUG0}WZ#NAkcNbeDlSH9nvy0&ukZ+nA&uQLaY1q<I-7X>K{uygYj9w4s<fiYjS~V6npBy2@%{Ja&CQST;Hy9R;i$CM^z|tuMkV3@+)T<OuR}_+oq<-sIN|{xe8!KgL)9cnz)c?RDL0}YVJfv8lelIkn^|?-F5`JN{_f_e>|~KA6;sWKg%mVPWAa=NQ^rIjNj7$;pkw8GjoJQ9{Wbm}Js&|B1`Us;K&oxvVX>h#>v6JR+FGqa6voxu_-Y=9v@?nCsWw!3MLbfxML~rAI%J5_DT=|TIBx^iYZ8<`F)*R|v|@sbifeI()lF5p)4Z`3E2KDTnBQrV7itX-oNUF%j^FC+&&MY>!DRH#1SW`RVEPKIR~*L_8cWGgJk8Q#y8%;bG?bS@gf-wThvxXAXZ}qy?{40kAJ0zd8syhzhrSFxOPud|g39f@>Ab9u-6ywpF{dZ7cam@_I)aQ9gB={Y9EoRyQ;FuxNP~!k@RN=|6-}{ZlyU844ef|Y&}amKsjy<7{~LWQIrIvER6`5;iw@dW2gJW^ZCzwFnL`DNYFx^L53H-joXH1C27<{!)if$`q~|ryUEbX}#+fkP&0I0fMDy-0OBnyd%0-cx_NLaN<Lg5E9M1ZT201I5y-(wNB!HZQ9}3nq5R);zXr`$EeHLPEHzAFk$@gyJkmuFbFhLF0XaQGp>RueHs7gukkO0g^nihO<sfkH?f`UmJ9AOetWu&Z1W7mrhF$UqN3p&yAsjwIaj??z+uBUvgq;CvDB2FAypgJ<^)GhfWwK+8~2n(t5^H4csBEwlwmbnHsPKymG6D~ERj&eilI60(#;7Ge9k!ZbbhD+>!>95v=Fdu|z#%-EMSk!jym*qhJwHz0p@U9^RM*(fN)#cfz&gx0q?ZP!LC@bO<(MeRTA4t)n_I}U$E|+DsUYysD)2m!mtE{4mylys30Ae?Amu9K@+r{t8gflSsJ6HG;CE3urJl8Bf5lf8qjcx}LTx!gBN6+_#g{^1dXlZj=yAXE`zPXq`Hb!4pm_1ZfwGPR+9Li%eaS^nR_*x|dX5$2krb9X_23J~&ZOv($wjvCNQNB>DyH=vBl?!UJF!lKI<cw&S>=i9xA-)(}SMfPE)AC+jH-R4L(v<olaD^W=y<Aj~?C<1~D?`C1yw~sIvL^NPiN}&dhun-u>yt{c%cBh9_?)@YbY}D1mr=3E&|7lyl(^_sXhZMJ#=;*72u|Ln4-rwf)@m*k{b}?*7FN^rz-81M%;f~MT(AnU%V?r(ICJv;^5*RFrYpNe15gi0($P7(Rfyis|FoWIn}l3jpHf>^8&Y-qt8v0bNc(DYWc|Z?TgD8`r>pmuZ@hm$sc)kUN=PS7z9hj?3z|?7@)<*{JAfXY_RP0FI-r5u#3ci}N=uGbV!Ja}Z`zY-uVBF695MUGnje#&vsto)?ga(s9wcermXt~|Ojg`6%U&GZAw5$QGt{ka4)+gUXb%9{IsN#`oAJZTzUp<(#m84usCPr02y6@5pgbg7xRFQ{*r}w-Nufb!HAA2HNsn)s&F59m%Tm1Yx1eh}`TA;HfXkI*^<<9KHzY2NvKYvUGFseis^pK0EEm)Iq)g>lALA&~)J%FET(vc^o*gIV^nXCVOIh+nWm1L&c4islORE5XM^lqd%{;g$PJhmdA{rpn9KSFZKqQaY&hd#kIOv-fFU{Kz&>9cvhf|c8HwyqNqezgazU$-3eSM4@er2w2p{Fxf>Qhp&e!x9=h+z)-T+g2`b^J-JH(^df8@hMl-yqr}jcu(?GDu(zw@a>-ttPF#vAHml&$*hZ@Rhi(y;mh-N*^!Zon2o?MTE-xBb6yGPZ1xVn>@&}XvIOKX)J#tmC#~AYfZy?U8TO@>coS~By#&eV!hAlLwq9{RQ;ZZiEpFf<I~*<Df{C0LX51lP3;!oB!qK2wR7*Oc#7LWICF5EfHG;u0jNAkE{ir~ycN{x;#`1tT50RtyRnuY)o%7xbTbh*b6#}~LsICh0B+A5r)j8JU4<$OGV$JqO3*!7il|>lY6V<V(rBgNw-N#&X<qsOu`hts5NVubp>c7qO#~QfR|l<wjWU3wsKy7BwXRVaqRaeY5UP!~&nbz^MV+^5iqq5EdRdP6x?5ALMPOg3cR?D8A9ce>ZH;Xhvr5t|2*S&i!en2PF~*5#Trh0Cj<U@VBYcBIk8`<2vIOItTA@{RP`G-3bx>WU<e^Q(_2lbnNy7x~n=8sg7)Wv3kIIe(&02(AuIwXo?rBF^czl*^s{R#^LM>SZ+D$+!jHMn5_W#9)cdUley7)v`^uZB$Fe?EhdpNRkwzgc41Mv0U)_P}vBlFYetu-bm-^R>R3go3r2}|T_@g0WFB>3vBU4CQEw`b-8+Wms;tE~};9hBF$VCRH0rjbZWV#8>{oGpGrtso?k6c)pz){F^JHlWFA`JJjB85=IpKR>qS40>UrNo8gP88Xxeq|lNplSwwZxcguQOyGw`Iw=QIA6Tk`)#b{Vas&-SbLT$UZ4y{smlADP4#QWq>}Qw^r2zo}F#V?YOMlC>5Nm5Nx?sccfWp))e3CQ{gmgM`wKWRNZ?x#meu2pF^{e$>@0ZV8YxSrsk$gGW|9)`r`>n0_qIe%|{iCO(g$aLxocE0m_T%;jPDc0;hfb{JM^bw9Bn&26dwIN=5cMLsu^gAeLB&T_Uy8z%HC?m{z{1)N;<dTOXp)p5T;n}0+SSzcm|sWUgXnkZ!-D%Lgwa{c;fA$vQu_E}@~dn_7dr3;${<Ky^?up<{0q~wDr?)yZS7d(vXPni*{vb`7NjgxF^1BEBOI#F<PFK_oY*ER-HAe28bR{@n=b1(4Ax0dlUn8Rs%zrM+{9-JJ({{~#K)!y;+ok=n?3+&RDn45{)K$$WIe6B6!tAXcW*Eys@N4FuUd05VA{x@0L8}UVAGQyz+uGqs5&w^)+x!UM|0r<#$jS}^M|s6<+%4m7N8An8b(UKF>mSQ6XTbw^sDJEQ@bTN11zgL>pL<ByQas^CSWNP3a1sdG#*<G7Wd4~&`vX-F~cZ_SoYx+Q%U%E*BoM?<7O(ECdYUUMivvICYp?pGun%Ff4n|6Z<ezH%Lnc5n&-RTUUR9CKPI%pQkevw?GWa?jF#FtJ&#2r#lQSoce2Y;?mQGI8_5p>`Sx4QVvtr+4Ct`P*Rsbr;`71&tHJ)kujh!6?myFmFVS0}@83u_^djPXf`e^$31{1kfqpF$?9$I83~^&qD2Wq?rT|}CsK~eu;cP!bH7s2Xw6LxA+V)q`ydBtFTe6nfd#8eWzr>DTQkQoucQvmswEv)kzs_8{me?cqkUMhENV_zirch|aZ9mXduFDjkA2DxussgJmHs8SgeD$dhsyg9xn%re6INK%`wvpcCh0P;Mn)jHTbTn1B#$rxl|CI__UkaLhGVxPYlsC~keccxLRC(`;LZ&vKyDES*S^n^3t;ED<kW>-@|0O7}Q-VhUcg+f}V`mVZc)Mk@<nUtppVnP^pP!Dv|FSuMC1$lqP{Tz-n`clUffp*?8Wfi4t)E_(CPg1%A>aIVti@=1b=0YRIc+Onh(C=vU9eE(Iuwd9IqPdWg|sF8SLz7I8|LeaF+(Zm4Ui;dWx1qt1|?>;bQ+9#K+hOw`RqXf;WREVA~A=>2_&7~AQ>{qfzxC;cn5wd0e-SuaIH_o^^ah@SX#PGbwmu3d)MYnO0-;FHG7ZHaiSKJn~W@^$XGx1RQ-hg41?5=?Z_U~8Kk3n*9tA<?F%~Z=%=}+c-d}c#d($0Q*3kF^+;S@5J8?s0Ng$<%(1kj{ZO$q$<|Uz$AXWn&Xc?PHVd(v3#w1m2@^l~%v+cO(6=*2e*YC}!6pi2b3|w0I0~_`k{i6hY=9wY<`FO*L3Aj=H*<|))Z+AO+QF*gvY8NpuuzuZQ5ltq{1cS<hzYe(dwBxc2pLC9Qb_inLMN)R#8k0ecW7qg30bkyJU2TsJ5aLMN-Fzi2P$*7MsHo+!BbF?A68jnpQxnngkH5>Ui;mVYuf4aj$x?<PqN_lZ6<m#lRDSCHf@%g57)E4WlaZLk5P$xvk)~*J>GAUJoy5AVdy_3#ez)z;FSon!(Ssj|Es6|l`>S~ydfPYm)cJi-&dk<e8`g}dp;FX5Y4l{NV8H3*FsAdDQDoZbISO<getqpMcItHjXlVY4#A5C2d}o`^lkY8OzLoO@cm{!^)NK!T}Wc%+D^hAoFZbG#}#17B|ULd*b@#)?<#a1%X}lQcKY>P^>`weVHEG(?7X(a%0KaHSF^%4kc01e=yXGIxz?d`U)yX{GOXf5^gT0S)Ic)dwg(8DL8G6YV%`(qzgOxBM{Dkof1!fnk{DdAt*<?HJxvqFxn0gsTYA!WRq)9&>a)QN{D%UmADX3k*QDkr!1~~`xxD^#a(r|A!5senI{|~s$ZNx^Lpu@o&f~Gwr-W8ry=*S&l;d%z-C+|akuazDV&<NHB_ye_R~Imi>Zb6?SI5xbC{?DbLD$Ekt3w}MWy2|5*GjxMJjLEKKHTd!|5TmoI7Z2X4B^FK|M}ox|JUg!zX88TUBtR*FZ)J45y}0hVfl|lCyTv+I0g^3fmav1dygnK=fy+Rt68Nj1^uhY<Kf_Ys8b~A`gB48;a7IpQH{QqU*M6rInO}bg;voSAF>HrmOHJqvv(iBlR^dY^D7WU&BOl-_x0-g&Y$eBA6RMH=JoLop!Qb$Kt2g%JvYVWjYJLCI*Bt;vdW_ExuU65nyWWw%7^s3(a@1A4r1==!|5k&H+7fX5;IwSltoCf<oNv&^vlqN?vxGY1S}^k80*#w)c<V}IOjUn-n4eMj9chwip`>u91u2{O>lyb+PsYyyGO?5ZoK_qUf@V${n*;!z8N>}d_y?bAsOTY>n_SEUOmNYFQNX|X*ts?3pnc1TtQB{A0-JSYb42UcW-k}$e~-ocd~+mgMGh*=g|_*XS0R&rJ=Wy0kR3S=qsyimg=>DKC>_+E;tK2gKo$xdF3WMl*tYcH_i1C!Zb-a5tlAx{6vQtlQ|g;y_2R-;=I(N;RqpnP9Kw0P0DU>!fS&)MWWOnvI_JO5dod?<!_4h#gx#__0_DN4rS~<nKGb?+}S6Phd%ce^Y#g=e@f<22kX1PnZlUH4MzMGllKX0{%Q);rUgrr@D)<k6*;!6Y3EwXx)YH4KyFrl(;^gYdIe7~UFlP|TwY%mc6vf7%xN`WT-^7*EDn79w9?iPuF<owNr^$=M95Igwr8$|E1S?d5hkI*6t9-6O<h+s`GftVm1H1c{McaO0<u>wnWw!!;5Tw*kKp8BcsP2Vz8JiG_1*V_-zUQno8j&c4x)e7Y_g4wKG?5pQs!)uRasW(0nof_z|W-f*p~xL^!ouON(Y$eU~m}yv+iJ_exr?j9`->0S~FSuk}w;LS+IAuQODn6ZbB1m%@CimkDD*@V$nJ#PHU~)sF|fRX466Gvc_;<U8=t|bQLj;O=c3d7hR=of$goyd9u`2n@~g=QpKbB5YK-rk0hqrO(&f#JEK{n`qYj&SD$46@W$_1-r8szgw^CRdSISJRG+`%`(wG)Iv{<};UNH0Av~T}tn6VB;=v_8i5fpE>yZFl=dugQ-xB>wkK=lNluyNqL7ht)ms@#wMG@n(`@HJO4ZHn6@ScZ+uL71XIacn>s^h*cR7R=CO6nuCn#*xmw_olmA38WP@94^nld<BKjZrA%nl)0#Vm3%mVQu{Q-{w+C(sHh8!Se;-7%nDg6R~W;P#=$S!k!20do;_w?ESXfCJ7n}S71R!ldC=U!^&VAmMRGn-<bE)zDx0vh({>GEE$1b#@%CX7TP<8ZQD~ao7rOGx>>Xx?<67C#dDr)x4&K#-x${%QVb=nWSf-QDrfKOoB4}%{RXL?XQDlbqlV=VVt9ODtA3&7vfLA<sBKipOQvi!Ev`m0%(Ocm)W>{A`Fg<u>AE%(s843*8eh0b9}fUeMNTE5O|wgAjpzB-IOqOv2#~bI)zZxxopl-LAcQ|3=WZVHu0hcw`2SiAVy4tFvQ;v}F%4AWJ7{en6zN|T&)A*g`34c<upHdPYnbj1@nU1BBn~LIsO$jnxfeiUwOgCl5#>ar;**Y@N#gE%axJo)%J};HPiH<IEg4m$tC!sxuyC8+##n`K9Vlg>>KT#r6k&7P31&xx5Glerc0E{$22Fx@O|}GntenCoS~kDlAt^|<Ho{$Ls~w+V*Y9*T^$m+V{QJ=7(O$d$(re7yJ0zsPIpf^!$&N<(hjLnMy7Xo5pHnsW@lW)hhg8jnX8*P79>+P-qbiJ7b)cbe5IPDMRrkIc`GHOqTHT+l-c{3=i)s{ca^id$fxqYKTq~fo5xGPiaom`c-S)J4Dt~tU$#0@N>5^H(QnYU<H++2OE8WW@7TGGZl98-QT;}I8L>n0SR|u$E%xd>h3Mg1Jg90$h*ym&N1lgeAc4AXFnXX6E0!0e@eucbybLkU7eLJ(p7n8ZVcfCW%>IFLV|IAhzzH(bx)lAdG?RlI$CJvrUGRUutmkTZWbXiiP+-J1;z9V15Cltgza?-WSk79ySA8DpF6l-Mj1U>t)6ZQGgl;kXVjD$K7HJ9KcyV36czM-OYajcc39uZgZf!@$l*Ym`d9&SDQiFQsB@XP{Z@<ff2MgeZ#n87;F5aGUwb!Hc1dziIsxIYYE54^tIxr?su-mj${ieoyc9ay#Qq}w2^y;zLb&D{EKl(U&+tqPa%Z6(^|!EjC3o<!*teL78iuY#w*wL24}?Y%FvbcNL2ruk;a(}7aJZrcb#nl*LS^T@>qzRB@hCULM}eW!E9rekNqIULA@-E??OPn<8|)>7ZOT^sq48oDdTvk=yMl9}Mxg46+cvI?{#$kEbV*D5$%vEoYR^ny5PF5EUbbm{0(n<^<}X>X1?`!Y>{Gv=JOg)8QS#vg;&up_mySo0!Xi$<v_mfTk9puucJX^(MvbAEN!ZFMLLi+ZoLduv>T&0XR*7=%Y#2Y@^E=Vf~fwDdEex>aiz<hV9l$L!|si&IM*4u<}e>$jWzuywd`s;Kut_XbXDF3wL+-<`>F&n{2Bv$fk&fI625H$j`7WCgP}f7p7iDOa7_L6is&_Wx&?sjn@@wdAQ;&VA{%Q+Qqu4qnD$TSLz5Ek$pRZ_W3dMGFJU#`P=R+}#LHFB9k9NV8?6oI(5fb)0-J=qA_EgsS4pm<&TacUdYj{Yd!_o4fp_d(B_JlYP?)hkkqiUt6M>6~3lSr;yzxdX%ImfHda}H2MRfkgQUb8?Nr&%crPy?U<EA+G?_trnQOQRlru8r8HgaUZBkjx*2_AUnR!lr~&YrC!XA1tW>)e-K<COjMavV-Q8$)q>9gypMAj^%TFaiEnkY>4M0@VtOdmEZm$d$LG4<LwpZ^-)v>=GT*qsH>R3VDDc6@O%+P(Wy|~M<KY{CLx+rc%+I%11h<+!1*UgKzXg^%`P3jVM>+4tBTUN<pA(URkWj3Ajq9CD~RMuLw1|~0hie5r%-haIL@bSjHet&gwe8U_n-r=nm4&EhsmYP3YzrSP%vX-3;p=g53?&W2Y);ny(Sh`k#+SgRG?Y=OQ>cgjuMOSRgP}O^SKd}!oZf*So%0XA(dO+h+XHv^k+&g%py+!A*O&Kepo0TNF3AY@389wmJz`%{D`q2X#lIHk6Z5ge!{RIPl-qLLF*O|>ze~DfC?3vloTY2@Sao$U{dt|QLi&dE)Kaoytauc;ge?t!doM}KwJ2Ys8_{QOmeT|eF3Y9bv=ZzPGk#G7MWL~&_uhWQiSLf*L@qx)cP2Ii3?F}_zo9hLeiX5$25Z2+^;|#U2aVSR>mbkO&0=n*{KD%z%NVVbEv0@hbtqhkd9Z`1HTD`b7IQ~!V_41Xw*BxxusEzQE3Rme0uBhuvLkKP(kYdF(ep;`^ca34F!L-*6x3%5ws?w?N%NSjyYd4H0ck7z>tjYBixIcX+tNL0YuO8OW{3+bBAnY(SVA*^-;ikJ6T$@n2r)?ZA4$_8H%`~cTCq0o1ttI9U$Zf*4MBKQ-f_En6*0oqvmQ=Y64<a}r-}z6XvHE="

_EXTRACTION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "memory": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                    "attributed_to": {
                        "type": "string",
                        "enum": ["user", "assistant"],
                    },
                    "linked_memory_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "id",
                    "text",
                    "attributed_to",
                    "linked_memory_ids",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["memory"],
    "additionalProperties": False,
}
_EXTRACTION_RESPONSE_FORMAT: dict[str, object] = {
    "type": "json_schema",
    "json_schema": {
        "name": "mem0_memory_extraction_v5",
        "strict": True,
        "schema": _EXTRACTION_SCHEMA,
    },
}


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError):
        _fail("managed_v5_live_extraction_projection_invalid")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


MEM0_V5_EXTRACTION_RESPONSE_FORMAT_SHA256 = _canonical_sha256(_EXTRACTION_RESPONSE_FORMAT)
MEM0_V5_EXTRACTION_SCHEMA_SHA256 = _canonical_sha256(_EXTRACTION_SCHEMA)
MEM0_V5_EXTRACTION_IMPLEMENTATION_SHA256 = _canonical_sha256(
    {
        "domain": MEM0_V5_EXTRACTION_IMPLEMENTATION_DOMAIN,
        "max_tokens": MEM0_V5_EXTRACTION_MAX_TOKENS,
        "max_source_content_bytes": _MAX_SOURCE_CONTENT_BYTES,
        "model": MEM0_V5_EXTRACTION_MODEL,
        "response_format_sha256": MEM0_V5_EXTRACTION_RESPONSE_FORMAT_SHA256,
        "response_schema_sha256": MEM0_V5_EXTRACTION_SCHEMA_SHA256,
        "system_prompt_sha256": MEM0_V5_EXTRACTION_SYSTEM_PROMPT_SHA256,
        "upstream": "mem0ai==2.0.15",
    }
)


class ManagedMem0V5ExtractionProjectionError(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
@dataclass(frozen=True, slots=True)
class PinnedMem0V5ExtractionRequestProjection:
    request_body_sha256: str
    request_body_bytes: int
    response_format_sha256: str
    response_schema_sha256: str
    requested_output_tokens: int

    def __post_init__(self) -> None:
        if (
            any(
                not is_sha256(value)
                for value in (
                    self.request_body_sha256,
                    self.response_format_sha256,
                    self.response_schema_sha256,
                )
            )
            or self.response_format_sha256 != MEM0_V5_EXTRACTION_RESPONSE_FORMAT_SHA256
            or self.response_schema_sha256 != MEM0_V5_EXTRACTION_SCHEMA_SHA256
            or type(self.request_body_bytes) is not int
            or not 1 <= self.request_body_bytes <= _MAX_EXTRACTION_REQUEST_BYTES
            or type(self.requested_output_tokens) is not int
            or self.requested_output_tokens != MEM0_V5_EXTRACTION_MAX_TOKENS
        ):
            _fail("managed_v5_live_extraction_projection_invalid")


@final
class PinnedMem0V5ExtractionRequestProjector:
    """Exact, provider-free Mem0 2.0.15 default extraction projector."""

    __slots__ = ()

    @property
    def implementation_domain(self) -> str:
        return MEM0_V5_EXTRACTION_IMPLEMENTATION_DOMAIN

    @property
    def implementation_sha256(self) -> str:
        return MEM0_V5_EXTRACTION_IMPLEMENTATION_SHA256

    def project(
        self,
        unit: ManagedMem0V5SourceUnit,
        *,
        current_date: str,
    ) -> PinnedMem0V5ExtractionRequestProjection:
        body = self.render_request_body(unit, current_date=current_date)
        return PinnedMem0V5ExtractionRequestProjection(
            request_body_sha256=hashlib.sha256(body).hexdigest(),
            request_body_bytes=len(body),
            response_format_sha256=MEM0_V5_EXTRACTION_RESPONSE_FORMAT_SHA256,
            response_schema_sha256=MEM0_V5_EXTRACTION_SCHEMA_SHA256,
            requested_output_tokens=MEM0_V5_EXTRACTION_MAX_TOKENS,
        )

    def render_request_body(
        self,
        unit: ManagedMem0V5SourceUnit,
        *,
        current_date: str,
    ) -> bytes:
        """Return the reviewed canonical bytes whose digest ``project`` binds."""

        if type(unit) is not ManagedMem0V5SourceUnit:
            _fail("managed_v5_live_extraction_projection_invalid")
        trusted_current_date = _iso_date(
            current_date,
            "managed_v5_live_extraction_current_date_invalid",
        )
        observation_date = _iso_date(
            unit.observation_date,
            "managed_v5_live_extraction_observation_date_invalid",
        )
        messages = _normalized_messages(unit)
        new_messages = "".join(item["role"] + ": " + item["content"] + "\n" for item in messages)
        user_prompt = "\n\n".join(
            (
                "## Summary\n",
                "## Last k Messages\n",
                "## Recently Extracted Memories\n[]",
                "## Existing Memories\n[]",
                "## New Messages\n" + new_messages,
                "## Observation Date\n" + observation_date,
                "## Current Date\n" + trusted_current_date,
                "# Output:",
            )
        )
        payload = {
            "max_tokens": MEM0_V5_EXTRACTION_MAX_TOKENS,
            "messages": [
                {"content": _system_prompt(), "role": "system"},
                {"content": user_prompt, "role": "user"},
            ],
            "model": MEM0_V5_EXTRACTION_MODEL,
            "response_format": _EXTRACTION_RESPONSE_FORMAT,
            "temperature": 0,
        }
        body = _canonical_json_bytes(payload)
        if not body or len(body) > _MAX_EXTRACTION_REQUEST_BYTES:
            _fail("managed_v5_live_extraction_request_too_large")
        return body


def _system_prompt() -> str:
    try:
        raw = zlib.decompress(base64.b85decode(_COMPRESSED_ADDITIVE_EXTRACTION_PROMPT_B85))
        if hashlib.sha256(raw).hexdigest() != MEM0_V5_EXTRACTION_SYSTEM_PROMPT_SHA256:
            raise ValueError
        return raw.decode("utf-8")
    except (ValueError, UnicodeDecodeError, zlib.error):
        _fail("managed_v5_live_extraction_prompt_pin_invalid")


def _normalized_messages(unit: ManagedMem0V5SourceUnit) -> tuple[dict[str, str], ...]:
    source = unit.source_messages
    if type(source) is not tuple or not 1 <= len(source) <= _MAX_SOURCE_MESSAGES:
        _fail("managed_v5_live_extraction_source_messages_invalid")
    normalized: list[dict[str, str]] = []
    for item in source:
        role = item.role
        content = item.content
        if (
            role not in {"user", "assistant"}
            or type(content) is not str
            or not content
            or len(content.encode("utf-8")) > _MAX_SOURCE_CONTENT_BYTES
        ):
            _fail("managed_v5_live_extraction_source_messages_invalid")
        normalized.append({"content": content, "role": role})
    return tuple(normalized)


def _iso_date(value: object, code: str) -> str:
    if type(value) is not str:
        _fail(code)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _fail(code)
    if parsed.isoformat() != value:
        _fail(code)
    return value


def _fail(code: str) -> None:
    raise ManagedMem0V5ExtractionProjectionError(code) from None


__all__ = (
    "MEM0_V5_EXTRACTION_IMPLEMENTATION_DOMAIN",
    "MEM0_V5_EXTRACTION_IMPLEMENTATION_SHA256",
    "MEM0_V5_EXTRACTION_MAX_TOKENS",
    "MEM0_V5_EXTRACTION_MODEL",
    "MEM0_V5_EXTRACTION_RESPONSE_FORMAT_SHA256",
    "MEM0_V5_EXTRACTION_SCHEMA_SHA256",
    "MEM0_V5_EXTRACTION_SYSTEM_PROMPT_SHA256",
    "ManagedMem0V5ExtractionProjectionError",
    "PinnedMem0V5ExtractionRequestProjection",
    "PinnedMem0V5ExtractionRequestProjector",
)
