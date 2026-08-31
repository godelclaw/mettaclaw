(= (iter-transform
      (coding-view $messages $advertised))
   (success
     (coding-view
       (coding-message-append-one
         $messages (coding-message user first))
       $advertised)))
